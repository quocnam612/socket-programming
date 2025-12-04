import sys, socket

from ServerWorker import ServerWorker

class Server:	
	
	def main(self):
		try:
			SERVER_PORT = int(sys.argv[1]) # read the first argument from command line (python Server.py Server_port)
		except:
			print("[Usage: Server.py Server_port]\n")
		rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # "AF_INET" means IPv4, "SOCK_STREAM" means TCP socket
		rtspSocket.bind(('', SERVER_PORT)) # Bind the socket to the server address and port ('' means all available interfaces)
		rtspSocket.listen(5) # Listen for up to 5 clients

		# Receive client info (address,port) through RTSP/TCP session
		while True:
			clientInfo = {} # create a dictionary to store client info
			clientInfo['rtspSocket'] = rtspSocket.accept() # new "rtspSocket" for each client ("rtspSocket" : (socket OBJECT, client address(IP, port)))
			ServerWorker(clientInfo).run() # init a ServerWorker object and run it

if __name__ == "__main__": # if the script is run directly (python Server.py)
	(Server()).main()


