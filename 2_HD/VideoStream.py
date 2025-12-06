class VideoStream:
	def __init__(self, filename): # Constructor
		self.filename = filename
		try:
			self.file = open(filename, 'rb') # read binary from file
		except:
			raise IOError # throw Input/Output error
		self.frameNum = 0
		self.lengthPrefixed = self.detectLengthPrefix()
		self.rawFrames = self.loadRawFrames()

	def nextFrame(self):
		"""Get next frame."""
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

	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum

	def detectLengthPrefix(self):
		pos = self.file.tell() # Save current file pointer
		peek = self.file.read(5) # Read first 5 bytes to check for length prefix
		self.file.seek(pos) # Reset file pointer
		return peek.isdigit()

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
	
