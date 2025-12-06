def loadRawFrames(self):
    content = self.file.read()
    frames = []
    start = content.find(b'\xff\xd8')
    while start != -1:
        end = content.find(b'\xff\xd9', start + 2)
        if end == -1:
            break
        frames.append(content[start:end + 2])
        start = content.find(b'\xff\xd8', end + 2)
    return frames