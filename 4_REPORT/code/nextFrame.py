def nextFrame(self):
    if self.lengthPrefixed:
        data = self.file.read(5)
        if data:
            framelength = int(data)
            data = self.file.read(framelength)
            self.frameNum += 1
        return data
    else:
        if self.frameNum < len(self.rawFrames):
            data = self.rawFrames[self.frameNum]
            self.frameNum += 1
            return data
        return None