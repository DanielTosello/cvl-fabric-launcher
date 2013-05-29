import os
import subprocess
import pexpect
import ssh
import wx
import wx.lib.newevent
import re
from StringIO import StringIO
import logging
from threading import *
import time

sshKeyGenBinary = "/usr/bin/ssh-keygen"
sshBinary = "/usr/bin/ssh"
sshAgentBinary = "/usr/bin/ssh-agent"
sshAddBinary = "/usr/bin/ssh-add"
sshKeyPath = "%s/.ssh/MassiveLauncherKey" % os.environ['HOME']


class KeyDist():

    def complete(self):
        self.completedLock.acquire()
        returnval = self.completed
        self.completedLock.release()
        return returnval

    class passphraseDialog(wx.Dialog):

        def __init__(self, parent, id, title, text, okString, cancelString):
            wx.Dialog.__init__(self, parent, id, title, style=wx.DEFAULT_FRAME_STYLE ^ wx.RESIZE_BORDER)
            self.SetTitle(title)
            self.panel = wx.Panel(self,-1)
            self.label = wx.StaticText(self.panel, -1, text)
            self.PassphraseField = wx.TextCtrl(self.panel, wx.ID_ANY, style=wx.TE_PASSWORD ^ wx.TE_PROCESS_ENTER)
            self.PassphraseField.SetFocus()
            self.Cancel = wx.Button(self.panel,-1,label=cancelString)
            self.OK = wx.Button(self.panel,-1,label=okString)

            self.sizer = wx.FlexGridSizer(2, 2, 5, 5)
            self.sizer.Add(self.label)
            self.sizer.Add(self.PassphraseField)
            self.sizer.Add(self.Cancel)
            self.sizer.Add(self.OK)

            self.PassphraseField.Bind(wx.EVT_TEXT_ENTER,self.onEnter)
            self.OK.Bind(wx.EVT_BUTTON,self.onEnter)
            self.Cancel.Bind(wx.EVT_BUTTON,self.onEnter)

            self.border = wx.BoxSizer()
            self.border.Add(self.sizer, 0, wx.ALL, 15)
            self.panel.SetSizerAndFit(self.border)
            self.Fit()
            self.password = None

        def onEnter(self,e):
            if (e.GetId() == self.Cancel.GetId()):
                self.canceled = True
                self.password = None
            else:
                self.canceled = False
                self.password = self.PassphraseField.GetValue()
            self.Close()
            self.Destroy()


            def getPassword(self):
                val = self.ShowModal()
                return self.password

    class startAgentThread(Thread):
        def __init__(self,keydistObject):
            Thread.__init__(self)
            self.keydistObject = keydistObject

        def run(self):
            agentenv = None
            try:
                agentenv = os.environ['SSH_AUTH_SOCK']
            except:
                try:
                    agent = subprocess.Popen(sshAgentBinary,stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True, universal_newlines=True)
                    stdout = agent.stdout.readlines()
                    for line in stdout:
                        match = re.search("^SSH_AUTH_SOCK=(?P<socket>.*); export SSH_AUTH_SOCK;$",line)
                        if match:
                            agentenv = match.group('socket')
                            os.environ['SSH_AUTH_SOCK']=agentenv
                except Exception as e:
                    string = "%s"%e
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_CANCEL,self,string)
            newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_LISTFINGERPRINTS,self.keydistObject)
            wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)

        class genkeyThread(Thread):
            def __init__(self,keydistObject):
                Thread.__init__(self)
                self.keydistObject = keydistObject

            def run(self):
                print "generating keys"
                keygencmd = sshKeyGenBinary + " -f " + self.keydistObject.sshKeyPath + " -C \"MASSIVE Launcher\""
                kg = pexpect.spawn(keygencmd,env={})
                kg.expect(".*pass.*")
                kg.send(self.keydistObject.password+"\n")
                kg.expect(".*pass.*")
                kg.send(self.keydistObject.password+"\n")
                kg.expect(pexpect.EOF)
                kg.close()
                try:
                    with open(self.keydistObject.sshKeyPath+".pub",'r'): pass
                    event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_AUTHFAIL,self.keydistObject) # Auth hasn't really failed but this event will trigger loading the key
                except:
                    event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_CANCEL,self.keydistObject,"error generating key")
                wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),event)
                print "generating exit"



        class listFingerprintsThread(Thread):
            def __init__(self,keydistObject):
                Thread.__init__(self)
                self.keydistObject = keydistObject

            def run(self):
                sshKeyListCmd = sshAddBinary + " -l "
                keylist = subprocess.Popen(sshKeyListCmd, stdout = subprocess.PIPE,stderr=subprocess.STDOUT,shell=True,universal_newlines=True)
                keylist.wait()
                stdout = keylist.stdout.readlines()
                self.keydistObject.fplock.acquire()
                self.keydistObject.fingerprints = []
                for line in stdout:
                    match = re.search("^[0-9]+\ (\S*)\ (.+)$",line)
                    if match:
                        self.keydistObject.fingerprints.append(match.group(1))
                if (self.keydistObject.pubkeyfp in self.keydistObject.fingerprints):
                    self.keydistObject.pubkeyloaded = True
                self.keydistObject.fplock.release()
                if (len(self.keydistObject.fingerprints) > 0):
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_TESTAUTH,self.keydistObject)
                else:
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_AUTHFAIL,self.keydistObject)
                wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)

        class testAuthThread(Thread):
            def __init__(self,keydistObject):
                Thread.__init__(self)
                self.keydistObject = keydistObject


            def run(self):
                sshCmd = sshBinary + " -o PasswordAuthentication=no -o PubkeyAuthentication=yes -l %s "%self.keydistObject.username + self.keydistObject.host
                ssh = pexpect.spawn(sshCmd)
                idx = ssh.expect(["Are you sure you want to continue","Permission denied",pexpect.EOF,".*"])
                if (idx == 0):
                    ssh.send("yes\n")
                    idx = ssh.expect(["Are you sure you want to continue","Permission denied",pexpect.EOF,".*"])
                if (idx in [1, 2]):
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_AUTHFAIL,self.keydistObject)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)
                else:
                    ssh.send("exit\n")
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_AUTHSUCCESS,self.keydistObject)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)
                    idx = ssh.expect([pexpect.EOF])
                ssh.close()


        class getPubkeyThread(Thread):
            def __init__(self,keydistObject):
                Thread.__init__(self)
                self.keydistObject = keydistObject

            def fingerprint(self):
                sshKeyGenCmd = sshKeyGenBinary + " -l -f " + self.keydistObject.sshKeyPath + ".pub"
                fp = subprocess.Popen(sshKeyGenCmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,shell=True,universal_newlines=True)
                stdout = fp.stdout.readlines()
                fp.wait()
                for line in stdout:
                    match = re.search("^[0-9]+\ (\S*)\ (.+)$",line)
                    if match:
                        fp = match.group(1)
                        comment = match.group(2)
                return fp,comment

            def loadKey(self):
                sshAddcmd = sshAddBinary + " " + self.keydistObject.sshKeyPath
                lp = pexpect.spawn(sshAddcmd)
                if (self.keydistObject.password != None and len(self.keydistObject.password) > 0):
                    passphrase = self.keydistObject.password
                else:
                    passphrase = ""
                idx = lp.expect(["Identity added",".*pass.*"])
                if (idx != 0):
                    lp.send(passphrase+"\n")
                    idx = lp.expect(["Identity added","Bad pass",pexpect.EOF])
                    if (idx == 0):
                        newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_LISTFINGERPRINTS,self.keydistObject)
                    if (idx == 1):
                        if (passphrase == ""):
                            newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_KEY_LOCKED,self.keydistObject)
                        else:
                            newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_KEY_WRONGPASS,self.keydistObject)
                    if (idx == 2):
                        newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_KEY_LOCKED,self.keydistObject)
                else:
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_KEY_LOCKED,self.keydistObject)
                wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)
                lp.close()


            def run(self):
                try:
                    f = open(sshKeyPath+".pub",'r')
                    f.close()
                    self.keydistObject.sshKeyPath = sshKeyPath
                    fp,comment = self.fingerprint()
                    self.keydistObject.pubkeyfp = fp
                    self.keydistObject.pubkeyComment = comment
                    self.keydistObject.fplock.acquire()
                    if (fp not in self.keydistObject.fingerprints):
                        self.loadKey()
                    else:
                        newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_LISTFINGERPRINTS,self.keydistObject)
                        wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)
                    self.keydistObject.fplock.release()

                except IOError:
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEWPASS_REQ,self.keydistObject)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),newevent)


        class CopyIDThread(Thread):
            def __init__(self,keydist):
                Thread.__init__(self)
                self.keydistObject = keydist

            def run(self):
                sshClient = ssh.SSHClient()
                sshClient.set_missing_host_key_policy(ssh.AutoAddPolicy())
                try:
                    sshClient.connect(hostname=self.keydistObject.host,username=self.keydistObject.username,password=self.keydistObject.password,allow_agent=False,look_for_keys=False)
                    stdin,stdout,stderr = sshClient.exec_command("mktemp")
                    tmpfile = stdout.read()
                    tmpfile = tmpfile.rstrip()
                    if (stderr.read() != ""):
                        raise Exception
                    sftp = sshClient.open_sftp()
                    sftp.put(self.keydistObject.sshKeyPath+".pub",tmpfile)
                    sftp.close()

                    sshClient.exec_command("module load massive")
                    sshClient.exec_command("/bin/mkdir -p ~/.ssh")
                    sshClient.exec_command("/bin/chmod 700 ~/.ssh")
                    sshClient.exec_command("/bin/touch ~/.ssh/authorized_keys")
                    sshClient.exec_command("/bin/chmod 600 ~/.ssh/authorized_keys")
                    sshClient.exec_command("/bin/cat %s >> ~/.ssh/authorized_keys"%tmpfile)
                    sshClient.exec_command("/bin/rm -f %s"%tmpfile)
                    sshClient.close()
                    event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_TESTAUTH,self.keydistObject)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),event)
                except ssh.AuthenticationException as e:
                    string = "%s"%e
                    event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_COPYID_NEEDPASS,self.keydistObject,string)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),event)
                except ssh.SSHException as e:
                    string = "%s"%e
                    event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_CANCEL,self.keydistObject,string)
                    wx.PostEvent(self.keydistObject.notifywindow.GetEventHandler(),event)



        class sshKeyDistEvent(wx.PyCommandEvent):
            def __init__(self,id,keydist,string=""):
                wx.PyCommandEvent.__init__(self,KeyDist.myEVT_CUSTOM_SSHKEYDIST,id)
                self.keydist = keydist
                self.string = string
            def copyid_complete(event):
                if (event.GetId() == KeyDist.EVT_COPYID_COMPLETE):
                    event.keydist.completedLock.acquire()
                    event.keydist.completed = True
                    event.keydist.completedLock.release()
                event.Skip()

            def copyid_fail(event):
                if (event.GetId() == KeyDist.EVT_COPYID_FAIL):
                    event.keydist.copyid(event.string)
                event.Skip()

            def test_authorised(event):
                if (event.GetId() == KeyDist.EVT_NOTAUTHORISED):
                    event.keydist.copyid()
                event.Skip()

            def loadkey(event):
                if (event.GetId() == KeyDist.EVT_LOADKEY_REQ):
                    event.keydist.loadKey()
                else:
                    event.Skip()


            def newkey(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_NEWPASS_REQ):
                    wx.CallAfter(event.keydist.getNewPassphrase_stage1,event.string)
                if (event.GetId() == KeyDist.EVT_KEYDIST_NEWPASS_RPT):
                    wx.CallAfter(event.keydist.getNewPassphrase_stage2)
                if (event.GetId() == KeyDist.EVT_KEYDIST_NEWPASS_COMPLETE):
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.workThread = KeyDist.genkeyThread(event.keydist)
                    event.keydist.workThread.start()
                event.Skip()

            def copyid(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_COPYID_NEEDPASS):
                    wx.CallAfter(event.keydist.getLoginPassword,event.string)
                if (event.GetId() == KeyDist.EVT_KEYDIST_COPYID):
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.workThread = KeyDist.CopyIDThread(event.keydist)
                    event.keydist.workThread.start()
                event.Skip()


            def cancel(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_CANCEL):
                    if (len(event.string)>0):
                        print event.string
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.completed=True
                event.Skip()

            def success(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_AUTHSUCCESS):
                    event.keydist.completed=True
                event.Skip()


            def needagent(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_NEEDAGENT):
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.workThread = KeyDist.startAgentThread(event.keydist)
                    event.keydist.workThread.start()
                else:
                    event.Skip()

            def listfingerprints(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_LISTFINGERPRINTS):
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.workThread = KeyDist.listFingerprintsThread(event.keydist)
                    event.keydist.workThread.start()
                else:
                    event.Skip()

            def testauth(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_TESTAUTH):
                    try:
                        if (event.keydist.workThread != None):
                            event.keydist.workThread.join()
                    except RuntimeError:
                        pass
                    event.keydist.workThread = KeyDist.testAuthThread(event.keydist)
                    event.keydist.workThread.start()
                else:
                    event.Skip()

            def keylocked(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_KEY_LOCKED):
                    wx.CallAfter(event.keydist.GetKeyPassword)
                if (event.GetId() == KeyDist.EVT_KEYDIST_KEY_WRONGPASS):
                    wx.CallAfter(event.keydist.GetKeyPassword,"Sorry that password was incorrect. ")
                event.Skip()


            def authfail(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_AUTHFAIL):
                    if(not event.keydist.pubkeyloaded):
                        try:
                            if (event.keydist.workThread != None):
                                event.keydist.workThread.join()
                        except RuntimeError:
                            pass
                        event.keydist.workThread = KeyDist.getPubkeyThread(event.keydist)
                        event.keydist.workThread.start()
                    else:
                        # if they key is loaded into the ssh agent, then authentication failed because the public key isn't on the server.
                        # *****TODO*****
                        # actually this might not be strictly true. gnome keychain (and possibly others) will report a key loaded even if its still locked
                        # we probably need a button that says "I can't remember my old keys password, please generate a new keypair"
                        newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_COPYID_NEEDPASS,event.keydist)
                        wx.PostEvent(event.keydist.notifywindow.GetEventHandler(),newevent)
                else:
                    event.Skip()


            def startevent(event):
                if (event.GetId() == KeyDist.EVT_KEYDIST_START):
                    newevent = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEEDAGENT,event.keydist)
                    wx.PostEvent(event.keydist.notifywindow.GetEventHandler(),newevent)
                else:
                    event.Skip()


        myEVT_CUSTOM_SSHKEYDIST=None
        EVT_CUSTOM_SSHKEYDIST=None
        def __init__(self,username,host,notifywindow):
            KeyDist.myEVT_CUSTOM_SSHKEYDIST=wx.NewEventType()
            KeyDist.EVT_CUSTOM_SSHKEYDIST=wx.PyEventBinder(self.myEVT_CUSTOM_SSHKEYDIST,1)
            KeyDist.EVT_KEYDIST_START = wx.NewId()
            KeyDist.EVT_KEYDIST_CANCEL = wx.NewId()
            KeyDist.EVT_KEYDIST_SUCCESS = wx.NewId()
            KeyDist.EVT_KEYDIST_NEEDAGENT = wx.NewId()
            KeyDist.EVT_KEYDIST_NEEDKEYS = wx.NewId()
            KeyDist.EVT_KEYDIST_LISTFINGERPRINTS = wx.NewId()
            KeyDist.EVT_KEYDIST_TESTAUTH = wx.NewId()
            KeyDist.EVT_KEYDIST_AUTHSUCCESS = wx.NewId()
            KeyDist.EVT_KEYDIST_AUTHFAIL = wx.NewId()
            KeyDist.EVT_KEYDIST_NEWPASS_REQ = wx.NewId()
            KeyDist.EVT_KEYDIST_NEWPASS_RPT = wx.NewId()
            KeyDist.EVT_KEYDIST_NEWPASS_COMPLETE = wx.NewId()
            KeyDist.EVT_KEYDIST_COPYID = wx.NewId()
            KeyDist.EVT_KEYDIST_COPYID_NEEDPASS = wx.NewId()
            KeyDist.EVT_KEYDIST_KEY_LOCKED = wx.NewId()
            KeyDist.EVT_KEYDIST_KEY_WRONGPASS = wx.NewId()

            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.cancel)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.success)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.needagent)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.listfingerprints)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.testauth)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.authfail)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.startevent)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.newkey)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.copyid)
            notifywindow.Bind(self.EVT_CUSTOM_SSHKEYDIST, KeyDist.sshKeyDistEvent.keylocked)

            self.completed=False
            self.username = username
            self.host = host
            self.notifywindow = notifywindow
            self.sshKeyPath = ""
            self.workThread = None
            self.pubkey = None
            self.pubkeyfp = None
            self.pubkeyloaded = False
            self.password = None
            self.fplock = Lock()
            self.completedLock = Lock()


        def GetKeyPassword(self,prepend=""):
            ppd = KeyDist.passphraseDialog(None,wx.ID_ANY,'Unlock Key',prepend+"Please enter the passphrase for the key","OK","Cancel")
            password = ppd.getPassword()
            if (password == None):
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_CANCEL,self)
            else:
                self.password = password
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_AUTHFAIL,self)
            wx.PostEvent(self.notifywindow.GetEventHandler(),event)

        def getLoginPassword(self,prepend=""):
            ppd = KeyDist.passphraseDialog(None,wx.ID_ANY,'Login Passphrase',prepend+"Please enter your login password for username %s at %s"%(self.username,self.host),"OK","Cancel")
            password = ppd.getPassword()
            self.password = password
            event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_COPYID,self)
            wx.PostEvent(self.notifywindow.GetEventHandler(),event)

        def getNewPassphrase_stage1(self,prepend=""):
            ppd = KeyDist.passphraseDialog(None,wx.ID_ANY,'New Passphrase',prepend+"Please enter a new passphrase","OK","Cancel")
            password = ppd.getPassword()
            if (len(password) < 6 and len(password)>0):
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEWPASS_REQ,self,"The password was too short. ")
            else:
                self.password = password
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEWPASS_RPT,self)
            wx.PostEvent(self.notifywindow.GetEventHandler(),event)

        def getNewPassphrase_stage2(self):
            ppd = KeyDist.passphraseDialog(None,wx.ID_ANY,'New Passphrase',"Please repeat the new passphrase","OK","Cancel")
            phrase = ppd.getPassword()
            if (phrase == None):
                phrase = ""
            if (phrase == self.password):
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEWPASS_COMPLETE,self)
            else:
                event = KeyDist.sshKeyDistEvent(KeyDist.EVT_KEYDIST_NEWPASS_REQ,self,"The passwords didn't match. ")
            wx.PostEvent(self.notifywindow.GetEventHandler(),event)


        def distributeKey(self):
            self.sshKeyPath="%s/.ssh/MassiveLauncherKey"%os.environ['HOME']
            event = KeyDist.sshKeyDistEvent(self.EVT_KEYDIST_START,self)
            wx.PostEvent(self.notifywindow.GetEventHandler(),event)