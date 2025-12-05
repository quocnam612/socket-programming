import threading

def sendRtspRequest(self, requestCode):
    if requestCode == self.SETUP and self.state == self.INIT:
        threading.Thread(target=self.recvRtspReply).start()
        self.rtspSeq += 1
        request = "SETUP " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nTransport: RTP/UDP; client_port= " + str(self.rtpPort)
        self.requestSent = self.SETUP
    elif requestCode == self.PLAY and self.state == self.READY:
        self.rtspSeq += 1
        request = "PLAY " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)
        self.requestSent = self.PLAY
    elif requestCode == self.PAUSE and self.state == self.PLAYING:
        self.rtspSeq += 1
        request = "PAUSE " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)
        self.requestSent = self.PAUSE
    elif requestCode == self.TEARDOWN and not self.state == self.INIT:
        self.rtspSeq += 1
        request = "TEARDOWN " + str(self.fileName) + " RTSP/1.0\nCSeq: " + str(self.rtspSeq) + "\nSession: " + str(self.sessionId)
        self.requestSent = self.TEARDOWN
    else:
        return
    
    self.rtspSocket.send(request.encode())
    print('\nData sent:\n' + request)