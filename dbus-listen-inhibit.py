#!/usr/bin/python
# vim: set fileencoding=utf8 :


import glib
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import threading
import Queue

import time
import datetime
import signal, sys

inhibits_list = {}

def exit_gracefully(signum, frame):
    # restore the original signal handler as otherwise evil things will happen
    # in raw_input when CTRL+C is pressed, and our signal handler is not re-entrant
    signal.signal(signal.SIGINT, original_sigint)

    print("Ctrl-C received, cleanning up.")
    mainloop.quit()

def proccess_signals (queue):
    global inhibits_list
    queueLock.acquire()
    if not queue.empty():
        data = dict(queue.get())
        queueLock.release()
        if data['member'] == "Inhibit":
            print ""
            pid = dbus.Interface(bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'), 'org.freedesktop.DBus').GetConnectionUnixProcessID(data['sender'])
            inhibits_list[data['sender']] = datetime.datetime.fromtimestamp(data['timestamp']).strftime('%Y-%m-%d %H:%M:%S') + " App = " + data['arg_0'] + " (pid: " + str(pid) + "), Reason = " + data['arg_1']
        elif data['member'] == "UnInhibit":
            print ""
            if data['sender'] in inhibits_list:
                del inhibits_list[data['sender']]
            #else:
                #print data['sender'], "wasn't registered"
        elif data['member'] == "HasInhibitChanged":
            if data['arg_0'] == True:
                # something Inhibits
                print "Power management inhibited"
            elif data['arg_0'] == False:
                # Nothing inhibits sleep
                print "Sleep possible"
                # There are cases that the proccess inhibitting sleep dies 
                # without notifying it, so we don't receive an UnInhibit 
                # but dbus keeps track of the callers, and if they die it 
                # releases the pending inhibits.
                # So at this point nothing is active and we should clear the list
                inhibits_list={}

    else:
        queueLock.release()
    if len(inhibits_list) > 0:
        print "Active Inhibits:"
        for value in sorted(inhibits_list.values()):
            print str(value)
    return False # So we are not scheduled to run again, 
                 # it'll be notification who'll reschedule us again



def notifications(bus, message):
    global workQueue
    if message.get_member() == "Inhibit" or message.get_member() == "UnInhibit" or message.get_member() == "HasInhibitChanged":
        queueLock.acquire()
        data = {"timestamp" : time.time(), "member": message.get_member(), "sender": message.get_sender()}
        for idx, arg in enumerate(message.get_args_list()):
            data['arg_' + str(idx)]=arg
        workQueue.put(data)
        queueLock.release()
        glib.idle_add(proccess_signals, workQueue) # schedule a call to proccess it when idle


# store the original SIGINT handler
original_sigint = signal.getsignal(signal.SIGINT)
signal.signal(signal.SIGINT, exit_gracefully)

queueLock = threading.Lock()
workQueue = Queue.Queue(10)

DBusGMainLoop(set_as_default=True)

bus = dbus.SessionBus()
bus.add_match_string_non_blocking("eavesdrop=true, path='/org/freedesktop/PowerManagement/Inhibit', interface='org.freedesktop.PowerManagement.Inhibit'")
bus.add_message_filter(notifications)

mainloop = glib.MainLoop()

mainloop.run()

print "Exiting"
