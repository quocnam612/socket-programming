data = self.rtpSocket.recv(20480)
if data:
    self.packetCount += 1
    self.bytesReceived += len(data)
    rtpPacket = RtpPacket()
    rtpPacket.decode(data)
    frameId = rtpPacket.timestamp()
    print("Current Frame Num: " + str(frameId))
    if frameId < self.frameNbr:
        continue
    if frameId > self.frameNbr:
        if self.frameNbr >= 0 and frameId - self.frameNbr > 1:
            self.frameLoss += frameId - self.frameNbr - 1
        self.frameNbr = frameId
        self.frameBuffer.clear()
    self.frameBuffer.extend(rtpPacket.getPayload())
    self.tryAssembleFrame()