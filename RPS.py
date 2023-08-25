# [NAME REDACTED] (B########)
# CSCI 4300: Operating Systems
# Rock Paper Scissors Source Code

import socket, threading, struct, sys, time
from traceback import format_exc
# these are struct.pack format strings- they dictate our packet format
TEXT_ENCODING = "utf-8"
PACK_GSTATE_F = "!BB12s12s50s"
PACK_GSTATE_S = struct.calcsize(PACK_GSTATE_F)
PACK_JOIN_F = "!12s"
PACK_JOIN_S = struct.calcsize(PACK_JOIN_F)
DIMS = (400,300)

# Game state is 2 bytes
# Byte 1
#   Bits 0-3: Player 1 move ID (0-15)
#   Bits 4-7: Player 2 move ID (0-15)
# Byte 2
# Bits 0-1, 2-3, 4-5: Point status
# 00: future round, 01: player point, 02: opponent point, 03: current round
# Bit 6: End game flag
# Bit 7: Hide action bar

# Game rules reference (which moves win against what and how)
magic_lose = "Magic is no\nmatch for sheer\nphysical violence."
rules = {
    1: {3: "Rock beats\nscissors!", 4: magic_lose},
    2: {1: "Paper covers\nrock!", 4: magic_lose},
    3: {2: "Scissors cut\npaper!", 4: magic_lose},
    4: {}
    }
# do not remove waiting
moveNames = ("Waiting...", "Rock", "Paper", "Scissors", "Magic..?")

# Game states
games=[]
gamesListLock = threading.Lock()
# Key is a client socket addr, value is socket obj and game list index
players={}

sv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
done=0
def ListenServer(hostname, port):
    # Create and configure TCP listen socket
    sv.bind((hostname, port))
    sv.listen(1)
    print(f"Listen server started at {hostname}:{port}")
    try:
        while not done:
            # Accept client and create client thread to handle it
            cl, addr = sv.accept()
            print("Got connection from", addr)
            t = threading.Thread(target=handleClient, args=(cl, addr), daemon=1)
            t.start()
    except:
        sv.close()


def handleClient(cl, addr):
    # All games are STATEFUL- when a client sends a message, we need
    # to perform the correct actions based solely on the GAME STATE.
    # Since we have two client threads for each game, these actions
    # must be symmetrical.
    
    # create gamestate if nonexistent or
    # accept MU if waiting gamestate exists
    cl.settimeout(5)
    try:
        if cl.recv(3) == b"RPS":
            pname = cl.recv(PACK_JOIN_S).strip(b'\x00').decode(TEXT_ENCODING)
            gamesListLock.acquire()
            ownPlayerID = 0
            lgid = len(games)-1 # creates potential race condition, so we lock beforehand
            
            # If there are no waiting games, create a new one
            if len(games)==0 or not games[lgid]['waiting']:
                gid = len(games)
                games.append({ # Default gamestate 
                    'waiting': True, # waiting for players?
                    'done': False, # game is over?
                    'rv': 0, # restart vote count (0b11=restart)
                    'addr1': addr,
                    'addr2': None,
                    'points': [0,0,0], #0 no point, 1 p1 point, 2 p2 point
                    'round': 0,
                    'move1': 0,
                    'move2': 0,
                    'score1': 0,
                    'score2': 0,
                    'name1': pname,
                    'name2': 'Player 2',
                    'lock': threading.Lock() # to prevent race condition in game
                })
                players[addr] = (cl, gid)
                ftext = "Waiting for\nplayer..."
            else:
                # If a waiting game exists, add our client!
                ownPlayerID = 1
                gid = lgid
                game = games[gid]
                game['addr2'] = addr
                game['name2'] = pname
                game['waiting'] = False
                players[addr] = (cl, gid)
                opp_sock = players[game['addr1']][0]
                gs_bin = packGamestate(
                    0,
                    games[gid],
                    f"{pname}\nconnected!"
                    )
                opp_sock.send(b'RPS' + gs_bin) # Tell the opponent we joined
                ftext = "Connected!"
            # Update client's UI
            cl.send(b'RPS'+packGamestate(ownPlayerID,games[gid],ftext))
            gamesListLock.release()
        else:
            cl.close()
    except socket.timeout:
        print(f"Server: Ding dong ditched by {addr}")
        return
    
    # Normal client handler loop begins here
    plstr = "2" if ownPlayerID else "1"
    oppstr = "1" if ownPlayerID else "2"
    game = games[gid]
    opp_sock = None
    try:
        # Create local utility function to send the gamestate
        # to both players - got tired of pasting it
        def updateAll(msg):
            cl.send(b'RPS'+packGamestate(ownPlayerID,game,msg))
            opp_sock.send(b'RPS'+packGamestate(not ownPlayerID,game,msg))
        while not done:
            cl.settimeout(None)
            header = cl.recv(3)
            if not header: # If we get no data, the connection has closed
                raise ConnectionResetError
            elif header == b'RPS':
                        
                cl.settimeout(10)
                move_id = int.from_bytes(cl.recv(1), 'big')
                
                # ============================
                # GAME LOGIC GOES HERE!!!!!!!
                # ============================

                opp_sock = players[games[gid][f'addr{oppstr}']][0]
                game['lock'].acquire()

                # If the game is done
                if game['done']:
                    # If not already voted, add my vote (bitwise)
                    if game['rv'] != ownPlayerID+1 and move_id == 0:
                        updateAll(f"{pname}\nwants a\nrematch!")
                        game['rv'] += (ownPlayerID+1)
                        # Are both votes in? If so, reset state
                        if game['rv'] >= 3:
                            game['done'] = False
                            game['rv'] = 0
                            game['points'] = [0,0,0]
                            game['round'] = 0
                            game['move1'] = 0
                            game['move2'] = 0
                            game['score1'] = 0
                            game['score2'] = 0
                            time.sleep(2)
                            updateAll("New game,\nbaby!")

                # If player hasn't already moved and the move is legal
                elif game[f"move{plstr}"] <= 0 and move_id in rules:
                    game[f"move{plstr}"] = move_id
                    # Create subjective copies of the gamestate for each player
                    opp_gs = dict(game)
                    pl_gs = dict(game)
                    
                    # If the opponent has already moved, the round is over
                    # Hide the other player's moves if it's not
                    roundover = game[f'move{oppstr}'] > 0
                    if not(roundover):
                        pl_gs[f"move{oppstr}"] = 0
                        opp_gs[f"move{plstr}"] = 0
                        
                    # Send subjective gamestates to clients
                    cl.send(b'RPS'+packGamestate(
                        ownPlayerID,
                        pl_gs,
                        f"You played\n{moveNames[move_id]}"
                        ))
                    opp_sock.send(b'RPS'+packGamestate(
                        not ownPlayerID,
                        opp_gs,
                        f"{pname}\nplayed."
                        ))
                    
                    # If both players have played, end the round,
                    # check to see if game is over, and act accordingly
                    if roundover:
                        # I should have made a Player data structure, but here I am
                        # with the worst if-else blocks I've ever written.
                        # This is TERRIBLE, but I don't have time to fix. Oh well!
                        opp_mv = game[f"move{oppstr}"]
                        opp_name = game[f"name{oppstr}"]
                        
                        if opp_mv in rules[move_id]: # Does client's move beat opponent move?
                            ftext = rules[move_id][opp_mv]
                            winmsg = f"{pname}\ngets the point!"
                            game[f'score{plstr}'] += 1
                            game['points'][game['round']] = ownPlayerID + 1
                            game['round'] += 1
                            
                        elif move_id in rules[opp_mv]: # Does opponent move beat client's move?
                            ftext = rules[opp_mv][move_id]
                            winmsg = f"{opp_name}\ngets the point!"
                            game[f'score{oppstr}'] += 1
                            game['points'][game['round']] = 2-ownPlayerID
                            game['round'] += 1
                            
                        else: # If not, it's a tie.
                            ftext = "Tie"
                            winmsg = "Nobody\ngets the point."
                            
                        for msg in (ftext, winmsg): #Broadcast flavor text & win message (2sec each)
                            time.sleep(2)
                            updateAll(msg)
                            
                        time.sleep(2)
                        # Create a game win message if either player has best 2 of 3
                        winmsg = None
                        if game[f'score{plstr}'] >= 2:
                            winmsg = f'{pname}\nwins!'
                        elif game[f'score{oppstr}'] >= 2:
                            winmsg = f'{opp_name}\nwins!'
                            
                        # End the game if a win message exists
                        if winmsg:
                            game['done'] = 1
                            updateAll(winmsg)
                        else: # Otherwise, reset moves and start new round
                            game[f"move{plstr}"] = 0
                            game[f"move{oppstr}"] = 0
                            updateAll("Choose your\nnext move.")

                # All changes have been made to the gamestate at this point,
                # so we can release its lock
                game['lock'].release() 

                # ==========================
                # END GAME LOGIC
                # ==========================
                
                
            else:
                print("Bad header from",addr,"- closing connection")
                cl.close()
                return
    except ConnectionResetError:
        print("Client connection reset, closing")
        try:
            cl.close()
        except OSError:
            pass #already closed at this point
        

def packGamestate(player, gs, ftext="notext"):
    # Does a lot of bitwise magic to pack the entire gamestate
    # into a couple of bytes and some strings.
    # Format is described at roughly line 14.
    # Result is usually sent over the network.
    # Notably, differs depending on which client it's being sent to,
    # so that the client always sees themselves on the left
    # and sees their own points as green.
    gs_byte = 0
    m_byte = 0
    p1 = "2" if player else "1"
    p2 = "1" if player else "2"
    p1a = gs[f'addr{p1}']
    p1n = gs[f'name{p1}']
    p1m = gs[f'move{p1}']
    p2a = gs[f'addr{p2}']
    p2n = gs[f'name{p2}']
    p2m = gs[f'move{p2}']
    m_byte |= p1m # Bits 0-3: Client move
    m_byte |= p2m << 4 # Bits 4-7: Opponent move
    # Choose red/green point icons based on player id
    gs_glyphs = (0b10, 0b01) if player else (0b01, 0b10)
    pcount = 0
    for i in range(len(gs['points'])):
        if gs['points'][i] > 0:
            gs_byte |= gs_glyphs[gs['points'][i]-1] << (2*i)
            pcount += 1
            
    # Only highlight the round if there's not already something there
    # Also sanity check to make sure it does not write into the bit flags
    if pcount <= gs['round'] and gs['round'] < 3:
        gs_byte |= (0b11 << (2*gs['round']))
        
    # Set "hide move UI" flag bit if player has already moved,
    # opponent has not yet connected, or the next round has not yet started
    if p1m > 0 or gs['waiting'] or pcount > gs['round']:
        gs_byte |= 128
    # Set the "show rematch button" flag bit if the game is over
    if gs['done']:
        gs_byte |= 64
    return struct.pack(
        PACK_GSTATE_F,
        m_byte,
        gs_byte,
        p1n.encode(TEXT_ENCODING),
        p2n.encode(TEXT_ENCODING),
        ftext.encode(TEXT_ENCODING)
        )

def startServerThread(hostname, port):
    svt = threading.Thread(target=ListenServer,args=(hostname,port),daemon=1)
    svt.start()
    txt_hostname.delete('1.0', tk.END)
    txt_hostname.insert(tk.END, hostname)
    txt_port.delete('1.0', tk.END)
    txt_port.insert(tk.END, str(port))
    btn_lan.grid_forget()



# CLIENTSIDE UI STUFF STARTS HERE!
# only run the remainder of the program if args != "server"!
# otherwise, immediately start listen server
if len(sys.argv) > 1 and sys.argv[1] == 'server':
    print("Starting dedicated server")
    try:
        ListenServer('', 23999)
    except KeyboardInterrupt:
        print("KeyboardInterrupt, closing socket")
        sv.close()
    sys.exit()

    
# Import the GUI library we'll be using
# We don't use this for dedicated servers
import tkinter as tk
root = tk.Tk()
root.title("Rock, Paper, Scissors")

# Load all of our images
thumb_waiting = tk.PhotoImage(file="thumbs/waiting.png")
thumb_unknown = tk.PhotoImage(file="thumbs/what.png")
thumbnails = { # player number, move id
    (0,0): thumb_waiting,
    (0,1): tk.PhotoImage(file="thumbs/rock.png"),
    (0,2): tk.PhotoImage(file="thumbs/paper.png"),
    (0,3): tk.PhotoImage(file="thumbs/scissors.png"),
    (0,4): tk.PhotoImage(file="thumbs/magic.png"),
    (1,0): thumb_waiting,
    (1,1): tk.PhotoImage(file="thumbs/rock2.png"),
    (1,2): tk.PhotoImage(file="thumbs/paper2.png"),
    (1,3): tk.PhotoImage(file="thumbs/scissors2.png"),
    (1,4): tk.PhotoImage(file="thumbs/magic2.png")
}

img_points = (
    tk.PhotoImage(file="thumbs/noPoint.png"),
    tk.PhotoImage(file="thumbs/plPoint.png"),
    tk.PhotoImage(file="thumbs/enePoint.png"),
    tk.PhotoImage(file="thumbs/onPoint.png")
    )

#create container for different "screen" frames- keep the screensize rigid
baseFrame = tk.Frame(root,width=DIMS[0],height=DIMS[1])
baseFrame.pack()

#region Build the connection screen UI
connectDiv = tk.Frame(baseFrame,width=DIMS[0],height=DIMS[1])
connectDiv.pack()
connectDiv.place(relx=0,rely=0,anchor="nw") #initialize this frame onscreen

# Title for the game
lbl_title = tk.Label(
    connectDiv,
    text="Rock, Paper, Scissors(, Magic)",
    font=("Arial Bold", 18),
    justify=tk.CENTER
    )
lbl_title.pack()
lbl_title.place(relx=0.5,rely=0.1,anchor="center")

# Create a content frame for connection settings
div_conInput = tk.Frame(connectDiv)
div_conInput.pack()
div_conInput.place(relx=0.5,rely=0.5,anchor="center")

# Username input field
lbl_uname = tk.Label(div_conInput,text="Username:",pady=5)
lbl_uname.grid(row=1,column=1)
txt_uname = tk.Text(div_conInput,height=1,width=20)
txt_uname.grid(row=1,column=2)
txt_uname.insert(tk.END, "Player")

# Hostname input field
lbl_hostname = tk.Label(div_conInput,text="Hostname:", pady=5)
lbl_hostname.grid(row=2,column=1)
txt_hostname = tk.Text(div_conInput,height=1,width=20)
txt_hostname.grid(row=2,column=2)

# Port input field
lbl_port = tk.Label(div_conInput,text="Port:", pady=5)
lbl_port.grid(row=3,column=1)
txt_port = tk.Text(div_conInput,height=1,width=20)
txt_port.grid(row=3,column=2)
txt_port.insert(tk.END, "23999")

# Create a target method for connect button
def cl_connect_gui():
    uname = txt_uname.get('1.0',tk.END).strip()
    hostname = txt_hostname.get('1.0',tk.END).strip()
    port = int(txt_port.get('1.0',tk.END).strip())
    clConnect(hostname, port, uname)

# Create the connect button
btn_connect = tk.Button(
    div_conInput,
    text="Connect",
    command=cl_connect_gui
    )
btn_connect.grid(row=4,column=1)

# Button to start a local server as a separate thread
btn_lan = tk.Button(
    div_conInput,
    text="Start Local Server",
    command=lambda h="localhost", p=23999: startServerThread(h,p)
    )
btn_lan.grid(row=4,column=2)

#endregion


#region Build the game UI
# Create a content frame for this "screen"
gameDiv = tk.Frame(baseFrame,width=DIMS[0],height=DIMS[1])
gameDiv.pack()
gameDiv.place(relx=0,rely=0,anchor="se") #hide this frame offscreen

# Add the flavor text label
lbl_gstate = tk.Label(gameDiv, text="Connecting\nto server...")
lbl_gstate.pack()
lbl_gstate.place(relx=0.5, rely=0.3, anchor='n')

# Add and place content frames for player portraits
p1div = tk.Frame(gameDiv)
p1div.pack()
p1div.place(relx = 0.25, rely = 0.1, anchor = 'n')
p2div = tk.Frame(gameDiv)
p2div.pack()
p2div.place(relx = 0.75, rely = 0.1, anchor = 'n')

# Add player 1's name, thumbnail, and move text
lbl_p1_name = tk.Label(p1div, text="Player 1")
thumb1 = tk.Label(p1div, image=thumb_unknown, borderwidth=3, relief="sunken")
lbl_p1_move = tk.Label(p1div, text="???")
lbl_p1_name.pack()
thumb1.pack()
lbl_p1_move.pack()

# Ditto for player 2
lbl_p2_name = tk.Label(p2div, text="Player 2")
thumb2 = tk.Label(p2div, image=thumb_unknown, borderwidth=3, relief="sunken")
lbl_p2_move = tk.Label(p2div, text="???")
lbl_p2_name.pack()
thumb2.pack()
lbl_p2_move.pack()

# Create a raised content frame for our point icons
div_points = tk.Frame(gameDiv, borderwidth=3, relief="raised")
div_points.pack()
div_points.place(relx=0.5, rely=0.05, anchor='n')

# Create the point icons & keep references to each
lbl_points = []
for i in range(3):
    nl = tk.Label(div_points,image=img_points[0])
    nl.pack(side=tk.LEFT)
    lbl_points.append(nl)

# Create a content frame for each move button
div_moves = tk.Frame(gameDiv, borderwidth=3, relief="sunken", padx=15, pady=15)
div_moves.pack()
div_moves.place(relx=0,rely=0,anchor="se") # initially hidden offscreen

# dynamically create move buttons menu based on the moveNames list
tk.Label(div_moves, text="Your moves:").pack()
for i in range(1, len(moveNames)):
    nb = tk.Button(
            div_moves,
            text=moveNames[i],
            command= lambda d=i: clSendMove(d),
            padx=10
        )
    nb.pack(side=tk.LEFT)

# Create a "rematch" button and hide it offscreen
btn_rematch = tk.Button(
    gameDiv,
    text="Rematch",
    command= lambda d=0: clSendMove(d), # sending move 0 is a "rematch" message
    padx=10)
btn_rematch.pack()
btn_rematch.place(relx=0,rely=0,anchor='se')
    

def setPlayerMove(p, index):
    # Update player portraits from images and move names based on move index
    (thumb1, thumb2)[p].configure(
        image=thumbnails.get( (p, index), thumb_unknown )
        )
    try: mn = moveNames[index]
    except IndexError: mn = "Invalid move...?"
    (lbl_p1_move, lbl_p2_move)[p].configure(text=mn)

def parseGamestate(movesByte, gstateByte, p1name, p2name, flavorText):
    # Update the UI based on the Gamestate packet sent by server
    
    # Set player portraits
    p1_mv_id = movesByte & 15
    p2_mv_id = (movesByte >> 4) & 15
    setPlayerMove(0, p1_mv_id)
    setPlayerMove(1, p2_mv_id)

    # Set correct point icons from the gamestate byte
    for i in range(3):
        p = lbl_points[i]
        pi = (gstateByte >> (2*i)) & 3
        p.configure(image=img_points[pi])

    # Update player name labels and the flavor text label
    p1n_str = p1name.strip(b'\x00').decode(TEXT_ENCODING)
    p2n_str = p2name.strip(b'\x00').decode(TEXT_ENCODING)
    ft_str = flavorText.strip(b'\x00').decode(TEXT_ENCODING)
    
    lbl_p1_name.configure(text=p1n_str)
    lbl_p2_name.configure(text=p2n_str)
    lbl_gstate.configure(text=ft_str)
    #TODO: UI for game over & no rematch button
    if gstateByte & 128:
        div_moves.place(relx=0,rely=0,anchor="se")
    else:
        div_moves.place(relx=0.5,rely=0.8,anchor="center")
    if gstateByte & 64:
        btn_rematch.place(relx=0.5,rely=0.7,anchor='center')
    else:
        btn_rematch.place(relx=0,rely=0,anchor='se')
    
#endregion

#region Client netcode

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def clSendMove(moveID):
    #print("sending move", moveID, "to the server")
    payload = int.to_bytes(moveID, 1, 'big')
    s.send(b'RPS' + payload)

def clConnect(hostname, port, uname="Player"):
    print("Starting client thread")
    s.connect((hostname, port))
    s.send(b'RPS'+struct.pack(
        PACK_JOIN_F,
        uname.encode(TEXT_ENCODING)
        ))
    t = threading.Thread(target=clThreadTarget, args=[s], daemon=True)
    t.start()
    print("Client thread started!")

def clThreadTarget(s):
    # This is the entire client thread.
    # It takes any packets that come in from the server,
    # and runs them through parseGamestate to update the UI
    # accordingly.
    # No other action is needed on the part of the client.
    try:
        while not done:
            s.settimeout(None)
            header = s.recv(3)
            if not header:
                raise ConnectionResetError
            elif header == b'RPS':
                s.settimeout(10)
                gs_bin = s.recv(PACK_GSTATE_S)
                gameDiv.place(anchor="nw") 
                connectDiv.place(anchor="se")
                data = struct.unpack(PACK_GSTATE_F, gs_bin)
                parseGamestate(*data)
    except ConnectionResetError:
        print("Connection reset :(")
    except:
        e_msg = ''.join(format_exc()).strip()
        print("Error in client thread:", e_msg)
    finally:
        try:
            s.close()
            print("Client socket closed")
            gameDiv.place(anchor="se") 
            connectDiv.place(anchor="nw")
        except:
            print("Client socket not closed- that's ok")
        
    
#endregion

try:
    root.mainloop()
except:
    e_msg = ''.join(format_exc()).strip()
    print("Error in main thread:", e_msg)
finally: 
    print("done test")
    sv.close()
    s.close()
# FIXME: all threads are daemon! This is VERY dirty!
# How does proper cleanup work with blocking threads in Python?
