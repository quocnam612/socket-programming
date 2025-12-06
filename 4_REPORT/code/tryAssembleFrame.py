SOI = b'\xff\xd8'
EOI = b'\xff\xd9'
def tryAssembleFrame(self):
    while True:
        start = self.frameBuffer.find(SOI)
        if start == -1:
            self.frameBuffer.clear()
            break
        end = self.frameBuffer.find(EOI, start + 2)
        if end == -1:
            if start > 0:
                del self.frameBuffer[:start]
            break
        frame = self.frameBuffer[start:end + 2]
        del self.frameBuffer[:end + 2]
        self.updateMovie(self.writeFrame(frame))