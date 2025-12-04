import sys
from tkinter import Tk
from Client import Client

if __name__ == "__main__": # if the script is run directly (python ClientLauncher.py)
	try:
		serverAddr = sys.argv[1] # read the first argument from command line (python ClientLauncher.py Server_name Server_port RTP_port Video_file)
		serverPort = sys.argv[2] # read the second argument from command line
		rtpPort = sys.argv[3] # read the third argument from command line
		fileName = sys.argv[4]	# read the fourth argument from command line
	except:
		print("[Usage: ClientLauncher.py Server_name Server_port RTP_port Video_file]\n")	
	
	root = Tk() # create a new Tkinter root window
	
	# Create a new client
	app = Client(root, serverAddr, serverPort, rtpPort, fileName)
	app.master.title("RTPClient")	
	root.mainloop() # start the Tkinter main loop to show the GUI window
	