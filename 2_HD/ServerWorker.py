from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

MTU = 1400  # conservative payload size for fragmentation

class ServerWorker:
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0 # 200: OK
	FILE_NOT_FOUND_404 = 1 # 404: Not Found
	CON_ERR_500 = 2 # 500: Internal Server Error
	
	clientInfo = {}
	
	def __init__(self, clientInfo):  # Constructor
		self.clientInfo = clientInfo
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start() # Thread(mini program) to receive RTSP request from the client
	
	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0] # "rtspSocket": (socket object(connSocket), addr)
		while True:            
			data = connSocket.recv(256) # wait for request from client (up to 256 bytes)
			if data:
				print("Data received:\n" + data.decode("utf-8"))
				self.processRtspRequest(data.decode("utf-8"))
	
	# Example of RTSP request from the client:
	# C: SETUP movie.Mjpeg RTSP/1.0
	# C: CSeq: 1
	# C: Transport: RTP/UDP; client_port=25000
	# S: RTSP/1.0 200 OK
	# S: CSeq: 1
	# S: Session: 123456
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')
		line1 = request[0].split(' ') 
		requestType = line1[0] # SETUP (from the example)
		
		# Get the media file name
		filename = line1[1] # movie.Mjpeg (from the example)
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ') # ['CSeq:', '1'] (from the example)
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = VideoStream(filename)
					self.state = self.READY
				except IOError:
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1])
				
				# Get the RTP/UDP port from the last line
				self.clientInfo['rtpPort'] = request[2].split(' ')[3] # client_port=25000 (from the example)
		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # socket(IPV4, UDP), UDP for RTP
				self.clientInfo['seqNum'] = 0
				
				self.replyRtsp(self.OK_200, seq[1])
				
				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event() # flag for pausing (set())/ resuming (or play(clear())) the video play
				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start() # begin execution of sendRtp() simultaneously
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set() # pause the video play
			
				self.replyRtsp(self.OK_200, seq[1])
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			self.clientInfo['event'].set() # pause/stop the video play
			
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close the RTP socket
			self.clientInfo['rtpSocket'].close() # shut down and release the socket
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			self.clientInfo['event'].wait(0.05) # wait 0.05 sec before sending next frame
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				fragments = [data[i:i + MTU] for i in range(0, len(data), MTU)]
				for idx, fragment in enumerate(fragments):
					if self.clientInfo['event'].isSet():
						break
					try:
						address = self.clientInfo['rtspSocket'][1][0] # "rtspSocket": (socket object, client address(clientAddr : (IP, port)))
						port = int(self.clientInfo['rtpPort'])
						self.clientInfo['seqNum'] += 1
						marker = 1 if idx == len(fragments) - 1 else 0
						packet = self.makeRtp(fragment, frameNumber, marker, self.clientInfo['seqNum'])
						self.clientInfo['rtpSocket'].sendto(packet, (address, port)) # sendto(data, (IP, port)) over UDP
					except:
						print("Connection Error")
						#print('-'*60)
						#traceback.print_exc(file=sys.stdout)
						#print('-'*60)

	def makeRtp(self, payload, frameNbr, marker, seqnum):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		pt = 26 # MJPEG type
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload, timestamp=frameNbr)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			connSocket = self.clientInfo['rtspSocket'][0] # "rtspSocket": (socket object(connSocket), addr)
			connSocket.send(reply.encode()) # send reply(convert to byte stream)
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")
