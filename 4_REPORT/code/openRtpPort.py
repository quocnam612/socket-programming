import socket, tkinter

def openRtpPort(self):
    self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.rtpSocket.settimeout(0.5)

    try:
        self.rtpSocket.bind(('', self.rtpPort))
    except:
        tkinter.messagebox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)
