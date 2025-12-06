class VideoStream:
	def __init__(self, filename): # Constructor
		self.filename = filename
		try:
			self.file = open(filename, 'rb') # read binary from file
		except:
			raise IOError # throw Input/Output error
		self.frameNum = 0
		
	def nextFrame(self):
		"""Get next frame."""
		data = self.file.read(5) # Get the framelength from the first 5 bits from where it is currently reading (if it's the first time, it reads from the start of the file)
		if data: 
			framelength = int(data)
							
			# Read the current frame
			data = self.file.read(framelength) # CONTINUE to read the next <framelength> bits which is the frame data (in bits)
			self.frameNum += 1
		return data
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	