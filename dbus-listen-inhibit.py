#!/usr/bin/python
# vim: set fileencoding=utf8 :
#
# Tool to check for dbus messages inhibiting sleep in power management. 
# It does so by listening for messages in the session dbus 
# inhibiting/uninhibiting power management, and the HasInhibitChanged
# message.
# 
# Changelog:
#
# 0.3
# Added the menu option to toggle the desktop notifications (helps a lot when
# using google hangouts to chat)
#
# 0.2
# Added the "gui", a systray icon with a right click menu that shows the active
# inhibits
#
# 0.1
# Console application only, first release.
#
# Copyright 2014 Jorge Nerín (jnerin@gmail.com)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation version 2 of the License.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import glib
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
import threading
import Queue

import time
import datetime
import signal, sys

import gtk
import pynotify


PROGRAM = "dbus-listen-inhibit"
VERSION = "0.3"
show_notifications = True;

inhibits_list = {}

def exit_gracefully(signum, frame):
    # restore the original signal handler as otherwise evil things will happen
    # in raw_input when CTRL+C is pressed, and our signal handler is not re-entrant
    signal.signal(signal.SIGINT, original_sigint)

    print("Ctrl-C received, cleanning up.")
    mainloop.quit()

def timestamp(timestamp):
    return datetime.datetime.fromtimestamp((timestamp)).strftime('%Y-%m-%d %H:%M:%S')

def proccess_signals (queue):
    global inhibits_list
    
    queueLock.acquire()
    if not queue.empty():
        data = dict(queue.get())
        queueLock.release()
        if data['member'] == "Inhibit":
            #print ""
            pid = dbus.Interface(bus.get_object('org.freedesktop.DBus', '/org/freedesktop/DBus'), 'org.freedesktop.DBus').GetConnectionUnixProcessID(data['sender'])
            inhibits_list[data['sender']] = timestamp(data['timestamp']) + " App = " + data['arg_0'] + " (pid: " + str(pid) + "), Reason = " + data['arg_1']
            desktop_notify("Inhibit started", inhibits_list[data['sender']])
        elif data['member'] == "UnInhibit":
            #print ""
            if data['sender'] in inhibits_list:
                print " " + timestamp(time.time()) + " finished: " + inhibits_list[data['sender']]
                desktop_notify("inhibit finished", inhibits_list[data['sender']])
                del inhibits_list[data['sender']]
            else:
                # Inhibit existed before we started
                print timestamp(time.time()) + " " + data['sender'] + " wasn't registered"
                desktop_notify("inhibit finished", data['sender'] + " wasn't registered")
        elif data['member'] == "HasInhibitChanged":
            if data['arg_0'] == True:
                # something Inhibits
                print timestamp(time.time()) + " Power management inhibited"
                SystrayIconApp.sleep_inhibitted(systray)
                
            elif data['arg_0'] == False:
                # Nothing inhibits sleep
                print timestamp(time.time()) + " Sleep possible"
                SystrayIconApp.sleep_possible(systray)
                # There are cases that the proccess inhibitting sleep dies 
                # without notifying it, so we don't receive an UnInhibit 
                # but dbus keeps track of the callers, and if they die it 
                # releases the pending inhibits.
                # Sadly if there are several pending inhibits we won't know
                # until HasInhibitChanged notifies us that there are 0 pending.
                # So at this point nothing is active and we should clear the list
                inhibits_list={}

    else:
        queueLock.release()

    dump_inhibits_text()

    return False # So we are not scheduled to run again, 
                 # it'll be notifications() who'll reschedule us again

def dump_inhibits_text():
    text=""
    if len(inhibits_list) > 0: # If we have pending inhibits show them
        print " Active Inhibits:"
        text = " Active Inhibits:\n"
        for value in sorted(inhibits_list.values(), reverse=True):
            print " " + str(value)
            text = text + " " + str(value) + "\n"
    return text



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


def desktop_notify(title, text):
    if show_notifications:
        n = pynotify.Notification (title, text)
        n.show ()


class SystrayIconApp:

    def __init__(self):
        self.icon = gtk.status_icon_new_from_stock(gtk.STOCK_ABOUT)
        # gtk.STOCK_YES gtk.STOCK_NO  
        self.icon.connect('popup-menu', self.on_right_click)
        self.icon.connect('activate', self.on_left_click)
        self.icon.set_tooltip((PROGRAM))

    def message(self, data=None):
      "Function to display messages to the user."
      
      msg=gtk.MessageDialog(None, gtk.DIALOG_MODAL,
        gtk.MESSAGE_INFO, gtk.BUTTONS_OK, data)
      msg.run()
      msg.destroy()
     
    def sleep_possible(self):
      self.icon.set_from_stock(gtk.STOCK_YES)
      self.icon.set_tooltip(('Sleep possible'))

    def sleep_inhibitted(self):
      self.icon.set_from_stock(gtk.STOCK_NO)
      self.icon.set_tooltip(('Power management inhibited'))
        
    def show_app(self, data=None):
      #self.message(data)
      TextView()

    def show_notifications_menu(self, data=None):
      global show_notifications
      #self.message(data)
      show_notifications=not show_notifications;

    def close_app(self, data=None):
      #self.message(data)
      gtk.main_quit()
     
    def make_menu(self, event_button, event_time, data=None):
      global show_notifications

      menu = gtk.Menu()
      show_item = gtk.MenuItem("Show status")
      show_notifications_item = gtk.CheckMenuItem("Show notifications")
      show_notifications_item.set_active(show_notifications)
      close_item = gtk.MenuItem("Exit")
      about_item = gtk.MenuItem("About")
      
      #Append the menu items  
      menu.append(show_item)
      menu.append(show_notifications_item)
      menu.append(close_item)
      menu.append(about_item)
      #add callbacks
      show_item.connect_object("activate", self.show_app, "Show status")
      show_notifications_item.connect_object("activate", self.show_notifications_menu, "Show notifications")
      close_item.connect_object("activate", self.close_app, "Close App")
      about_item.connect_object("activate", self.show_about_dialog, "About")
      #Show the menu items
      show_item.show()
      show_notifications_item.show()
      close_item.show()
      about_item.show()
      
      #Popup the menu
      menu.popup(None, None, None, event_button, event_time)
     
    def on_right_click(self, data, event_button, event_time):
      self.make_menu(event_button, event_time)
     
    def on_left_click(self, event):
      #self.message("Status Icon Left Clicked")
      self.show_app()
     

    def  show_about_dialog(self, data=None):
        about_dialog = gtk.AboutDialog()
        about_dialog.set_destroy_with_parent (True)
        about_dialog.set_icon_name (PROGRAM)
        about_dialog.set_name(PROGRAM)
        about_dialog.set_version(VERSION)
        about_dialog.set_copyright("(C) 2014 Jorge Nerín")
        about_dialog.set_comments(("Program to listen for dbus power management inhibit related messages to help debugging sleep problems, comes with a system tray icon"))
        about_dialog.set_authors(['Jorge Nerín <jnerin@gmail.com>'])
        about_dialog.run()
        about_dialog.destroy()


class TextView:
    def close(self, widget):
        #gtk.main_quit()
        self.window.destroy()

    def close_application(self, widget):
        self.window.destroy()

    def set_text(text):
        self.textbuffer.set_text(text)

    def __init__(self):
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_resizable(True)  
        self.window.connect("destroy", self.close_application)
        self.window.set_title("Inhibit dump")
        self.window.set_border_width(0)
        self.window.set_default_size(500, 200)

        box1 = gtk.VBox(False, 0)
        self.window.add(box1)
        box1.show()

        box2 = gtk.VBox(False, 10)
        box2.set_border_width(10)
        box1.pack_start(box2, True, True, 0)
        box2.show()

        sw = gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        textview = gtk.TextView()
        self.textbuffer = textview.get_buffer()
        sw.add(textview)
        sw.show()
        textview.set_editable(False)
        textview.show()

        box2.pack_start(sw)
        self.textbuffer.set_text(dump_inhibits_text())

        separator = gtk.HSeparator()
        box1.pack_start(separator, False, True, 0)
        separator.show()

        box2 = gtk.VBox(False, 10)
        box2.set_border_width(10)
        box1.pack_start(box2, False, True, 0)
        box2.show()

        button = gtk.Button("close")
        button.connect("clicked", self.close_application)
        box2.pack_start(button, True, True, 0)
        button.set_flags(gtk.CAN_DEFAULT)
        button.grab_default()
        button.show()
        self.window.show()




if __name__ == '__main__':

    # store the original SIGINT handler
    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, exit_gracefully)

    systray = SystrayIconApp()    
    #gtk.main()

    if not pynotify.init (PROGRAM):
        sys.exit (1)

    queueLock = threading.Lock()
    workQueue = Queue.Queue(10)

    DBusGMainLoop(set_as_default=True)

    bus = dbus.SessionBus()
    bus.add_match_string_non_blocking("eavesdrop=true, path='/org/freedesktop/PowerManagement/Inhibit', interface='org.freedesktop.PowerManagement.Inhibit'")
    bus.add_message_filter(notifications)

    status = bus.get_object("org.freedesktop.PowerManagement", "/org/freedesktop/PowerManagement/Inhibit").HasInhibit()

    if status:
        print timestamp(time.time()) + " Power management inhibited since unknown"
        SystrayIconApp.sleep_inhibitted(systray)
    else:
        print timestamp(time.time()) + " Sleep possible since unknown"
        SystrayIconApp.sleep_possible(systray)

    #mainloop = glib.MainLoop()
    #mainloop.run()
    
    gtk.main()

    print "Exiting"
