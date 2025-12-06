MAX_PAYLOAD = 1500

def sendRtp(self):
    while True:
        self.clientInfo['event'].wait(0.05)
        
        if self.clientInfo['event'].isSet(): 
            break 
        data = self.clientInfo['videoStream'].nextFrame()
        if data: 
            try:
                frameNumber = self.clientInfo['videoStream'].frameNbr()
                address = self.clientInfo['rtspSocket'][1][0]
                port = int(self.clientInfo['rtpPort'])
                for start in range(0, len(data), MAX_PAYLOAD):
                    if self.clientInfo['event'].isSet():
                        break
                    fragment = data[start:start + MAX_PAYLOAD]
                    self.seqNum += 1
                    packet = self.makeRtp(fragment, self.seqNum, frameNumber)
                    self.clientInfo['rtpSocket'].sendto(packet, (address, port))
            except:
                print("Connection Error")