class VideoStream:
	def __init__(self, filename): # Constructor
		self.filename = filename
		try:
			self.file = open(filename, 'rb') # read binary from file
		except:
			raise IOError # throw Input/Output error
		self.frameNum = 0
		
		self.lengthPrefixed = self._detectLengthPrefix()
		if not self.lengthPrefixed:
			self.rawFrames = self._loadRawFrames()
			self.totalFrames = len(self.rawFrames)
		else:
			self.rawFrames = None
			self.totalFrames = None

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
			if self.rawFrames and self.frameNum < len(self.rawFrames):
				frame = self.rawFrames[self.frameNum]
				self.frameNum += 1
				return frame
			return b''

	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum

	def _detectLengthPrefix(self):
		pos = self.file.tell()
		peek = self.file.read(5)
		self.file.seek(pos)
		return peek.isdigit()

	def _loadRawFrames(self):
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
	
