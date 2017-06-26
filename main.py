#!/usr/bin/env python

import kivy
kivy.require('1.10.0')
from kivy.app import App
from kivy.support import install_twisted_reactor
from kivy.config import Config
from kivy.logger import Logger
from kivy.graphics import Color,Rectangle
from kivy.core.image import Image as CoreImage
from kivy.metrics import Metrics, sp
from kivy.uix.widget import Widget
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image,AsyncImage
from kivy.uix.popup import Popup
from mpd import MPDProtocol
import os
import traceback
import mutagen
import io

#install twisted reactor to interface with mpd
import sys
if 'twisted.internet.reactor' in sys.modules:
    del sys.modules['twisted.internet.reactor']
install_twisted_reactor()
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import task
from twisted.internet.defer import inlineCallbacks

from mpdfactory import MPDClientFactory
from extra import ScrollButton,ScrollBoxLayout,songratings
from playlistpanel import PlaylistTabbedPanelItem

class KmpcInterface(TabbedPanel):

    def __init__(self,config):
        super(self.__class__,self).__init__()
        self.config = config
        # set up mpd connection
        self.factory = MPDClientFactory()
        self.factory.connectionMade = self.mpd_connectionMade
        self.factory.connectionLost = self.mpd_connectionLost
        reactor.connectTCP(self.config.get('mpd','host'), self.config.getint('mpd','port'), self.factory)
        # bind callbacks for tab changes
        self.bind(current_tab=self.main_tab_changed)
        self.mpd_status={'state':'stop','repeat':0,'single':0,'random':0,'consume':0,'curpos':0}
        self.update_slider=True
        self.currsong=None
        self.nextsong=None
        self.currfile=None

    def mpd_connectionMade(self,protocol):
        self.protocol = protocol
        self.ids.playlist_tab.protocol=protocol
        self.ids.library_tab.protocol=protocol
        Logger.info('Application: Connected to mpd server host='+self.config.get('mpd','host')+' port='+self.config.get('mpd','port'))
        # start the interface update task after mpd connection
        self.status_task=task.LoopingCall(self.protocol.status)
        self.status_task.start(1.0)
        # run the callbacks once to update the interface
        self.protocol.currentsong().addCallback(self.update_mpd_currentsong).addErrback(self.handle_mpd_error)
        # for some reason the next line causes an exception. it looks like it is trying to call MPDIdleHandler.__call__ instead, which is super weird
        # so instead we run it once when the active_tab changes to Playlist
#        self.protocol.playlistinfo().addCallback(self.ids.playlist_tab.populate_playlist).addErrback(self.ids.playlist_tab.handle_mpd_error)

    def main_tab_changed(self,obj,value):
        self.active_tab = value.text
        Logger.info("Application: Changed active tab to "+self.active_tab)
        if self.active_tab == 'Now Playing':
            # this is just to ensure the interface gets updated as soon as possible
            if 'protocol' in locals():
                self.protocol.status()
        elif self.active_tab == 'Playlist':
            # switching to the playlist tab repopulates it if it is empty
            if len(self.ids.playlist_tab.rv.data) == 0:
                self.protocol.playlistinfo().addCallback(self.ids.playlist_tab.populate_playlist).addErrback(self.ids.playlist_tab.handle_mpd_error)

    def mpd_connectionLost(self,protocol, reason):
        Logger.warn('Application: Connection lost: %s' % reason)

    def current_track_slider_up(self):
        curpos=int(self.ids.current_track_slider.value)
        Logger.info('Application: current_track_slider_up('+str(curpos)+')')
        self.update_slider=False
        self.protocol.seekcur(str(curpos)).addErrback(self.handle_mpd_error)
        self.update_slider=True

    def current_track_slider_move(self):
        Logger.info('Application: current_track_slider_move()')
        self.update_slider=False

    def handle_mpd_error(self,result):
        Logger.error('Application: MPDIdleHandler Callback error: {}'.format(result))

    def stop_zero_stuff(self):
        self.ids.current_track_time_label.text=''
        self.ids.current_track_totaltime_label.text=''
        self.ids.current_track_slider.value=0
        self.ids.current_playlist_track_number_label.text=''
        self.ids.current_song_label.text = 'Playback Stopped'
        self.ids.current_artist_label.text = ''
        self.ids.current_album_label.text = ''
        self.ids.next_track_label.text = ''
        self.ids.next_song_artist_label.text = ''
        self.currfile = None
        self.currsong = None
        self.nextsong = None
        self.ids.song_star_layout.clear_widgets()
        self.ids.album_cover_layout.clear_widgets()
        self.ids.album_cover_layout.size_hint_min_x=None

    def update_mpd_status(self,result):
        Logger.debug('NowPlaying: update_mpd_status()')
        # probably state is the only one necessary, but hey
        self.mpd_status['state']=result['state']
        self.mpd_status['repeat']=result['repeat']
        self.mpd_status['single']=result['single']
        self.mpd_status['random']=result['random']
        self.mpd_status['consume']=result['consume']
        if self.mpd_status['state'] == 'stop':
            # if stopped, there are no current or next songs
            self.currsong=None
            self.nextsong=None
        else:
            # save current song, this is a 0-based index into the playlist
            self.currsong=result['song']
            # save next song, this is a 0-based index into the playlist
            if 'nextsong' in result:
                self.nextsong=result['nextsong']
                self.protocol.playlistinfo(self.nextsong).addCallback(self.update_mpd_nextsong).addErrback(self.handle_mpd_error)
            else:
                self.nextsong=None
        # check various flag states. there's probably a more efficient way to do this
        if int(self.mpd_status['repeat']):
            self.ids.repeat_button.state='down'
        else:
            self.ids.repeat_button.state='normal'
        if int(self.mpd_status['single']):
            self.ids.single_button.state='down'
        else:
            self.ids.single_button.state='normal'
        if int(self.mpd_status['random']):
            self.ids.random_button.state='down'
        else:
            self.ids.random_button.state='normal'
        if int(self.mpd_status['consume']):
            self.ids.consume_button.state='down'
        else:
            self.ids.consume_button.state='normal'
        if self.mpd_status['state']=='pause' or self.mpd_status['state']=='stop':
            self.ids.play_button.state='normal'
            self.ids.play_button.text=u"\uf04b"
        else:
            self.ids.play_button.state='down'
            self.ids.play_button.text=u"\uf04c"
        if self.mpd_status['state'] == 'stop':
            # zero everything out if we are stopped
            self.stop_zero_stuff()
        else:
            # mpd returns {elapsed seconds}:{total seconds}, the following splits each to minute:second
            c,t=result['time'].split(":")
            cm,cs=divmod(int(c),60)
            tm,ts=divmod(int(t),60)
            self.ids.current_track_time_label.text = "%02d:%02d" % (cm,cs)
            self.ids.current_track_totaltime_label.text = "%02d:%02d" % (tm,ts)
            # set the max slider value to the total seconds
            self.ids.current_track_slider.max = int(t)
            # set the current slider value to the current seconds
            self.mpd_status['curpos']=int(c)
            if self.update_slider:
                self.ids.current_track_slider.value = int(c)
            # throws an exception if i don't do this
            a=int(result['song'])+1
            b=int(result['playlistlength'])
            self.ids.current_playlist_track_number_label.text = "%d of %d" % (a,b)

    def update_mpd_currentsong(self,result):
        Logger.debug('NowPlaying: update_mpd_currentsong()')
        if result:
            # set the song title and artist labels
            self.ids.current_song_label.text = result['title']
            self.ids.current_artist_label.text = result['artist']
            # clear the album cover
	    self.ids.album_cover_layout.clear_widgets()
            # set the current file name
            self.currfile = result['file']
            # get the stored star rating
            self.protocol.sticker_get('song',self.currfile,'rating').addCallback(self.update_mpd_sticker_rating).addErrback(self.handle_mpd_no_sticker)
            # figure out the full path of the file
            bp=self.config.get('mpd','basepath')
            p=os.path.join(bp,result['file'])
            # set the release year if mpd has it
            year=None
            if 'date' in result:
                year=result['date'][:4]
            if os.path.isfile(p):
                Logger.debug('NowPlaying: found good file at path '+p)
                # load up the file to read the tags
                f = mutagen.File(p)
                cimg = None
                data = None
                # if the original year mp3 tag exists use it instead of mpd's year
                if 'TXXX:originalyear' in f.keys():
                    year=format(f['TXXX:originalyear'])
                try:
                    # try to get mp3 cover, if this throws an exception it's not an mp3 or it doesn't have a cover
                    pframes = f.tags.getall("APIC")
                    for frame in pframes:
                        ext = 'img'
                        if frame.mime.endswith('jpeg') or frame.mime.endswith('jpg'):
                            ext = 'jpg'
                        elif frame.mime.endswith('png'):
                            ext = 'png'
                        elif frame.mime.endswith('bmp'):
                            ext = 'bmp'
                        elif frame.mime.endswith('gif'):
                            ext = 'gif'
                        data=io.BytesIO(bytearray(frame.data))
                        break
                except AttributeError:
                    pass
                # try to get mp4 cover
                if 'covr' in f.keys():
                    if f['covr'][0].imageformat == mutagen.mp4.MP4Cover.FORMAT_PNG:
                        ext = 'png'
                    else:
                        ext = 'jpg'
                    data=io.BytesIO(bytearray(f['covr'][0]))
                if data:
                    # if we got image data, load it as a kivy.core.image
                    cimg = CoreImage(data,ext=ext)
                if cimg:
                    # if the image loading worked, create an image widget and fix up the layout
		    img=AsyncImage(texture=cimg.texture,allow_stretch=True)
		    self.ids.album_cover_layout.add_widget(img)
                    self.ids.album_cover_layout.size_hint_min_x=sp(300)
                else:
                    # if no coreimage, make the album layout tiny
                    self.ids.album_cover_layout.size_hint_min_x=None
            else:
                Logger.debug('NowPlaying: no file found at path '+p)
            # if we got a year tag from somewhere, include it in the album label
            if year:
                self.ids.current_album_label.text = result['album']+' ['+year+']'
            else:
                self.ids.current_album_label.text = result['album']
        else:
            # there's not a current song, so zero everything out
            self.stop_zero_stuff()

    def update_mpd_sticker_rating(self,result):
        Logger.debug('NowPlaying: update_mpd_sticker_rating')
        btn = Button(padding_x='10sp',font_name='resources/FontAwesome.ttf',halign='center',valign='middle')
        btn.text = songratings[result]['stars']
	btn.bind(on_press=self.rating_popup)
	self.ids.song_star_layout.clear_widgets()
	self.ids.song_star_layout.add_widget(btn)

    def handle_mpd_no_sticker(self,result):
        Logger.debug('NowPlaying: handle_mpd_no_sticker')
        btn = Button(padding_x='10sp',font_name='resources/FontAwesome.ttf',halign='center',valign='middle')
        btn.text = u"\uf29c"
	btn.bind(on_press=self.rating_popup)
	self.ids.song_star_layout.clear_widgets()
	self.ids.song_star_layout.add_widget(btn)

    def update_mpd_nextsong(self,result):
        Logger.debug('NowPlaying: update_mpd_nextsong()')
        self.ids.next_track_label.text = 'Up Next:'
        for obj in result:
            self.ids.next_song_artist_label.text = obj['artist']+' - '+obj['title']

    def prev_pressed(self):
        Logger.debug('Application: prev_pressed()')
        self.protocol.previous()

    def play_pressed(self):
        Logger.debug('Application: play_pressed()')
        if self.mpd_status['state'] == 'play':
            self.protocol.pause()
        else:
            self.protocol.play()

    def next_pressed(self):
        Logger.debug('Application: next_pressed()')
        self.protocol.next()

    def repeat_pressed(self):
        Logger.debug('Application: repeat_pressed()')
        self.protocol.repeat(str(1-int(self.mpd_status['repeat'])))

    def single_pressed(self):
        Logger.debug('Application: single_pressed()')
        self.protocol.single(str(1-int(self.mpd_status['single'])))

    def random_pressed(self):
        Logger.debug('Application: random_pressed()')
        self.protocol.random(str(1-int(self.mpd_status['random'])))

    def consume_pressed(self):
        Logger.debug('Application: consume_pressed()')
        self.protocol.consume(str(1-int(self.mpd_status['consume'])))

    def rating_popup(self,instance):
        Logger.debug('Application: rating_popup()')
        layout = GridLayout(cols=2,spacing=10)
        popup = Popup(title='Rating',content=layout,size_hint=(0.8,1))
        for r in list(range(0,11)):
            btn=Button(font_name='resources/FontAwesome.ttf')
            btn.text=songratings[str(r)]['stars']
            btn.rating=str(r)
            btn.popup=popup
            layout.add_widget(btn)
            btn.bind(on_press=self.rating_set)
            lbl=Label(text=songratings[str(r)]['meaning'],halign='left')
            layout.add_widget(lbl)
        popup.open()

    def rating_set(self,instance):
        Logger.debug('Application: rating_set('+instance.rating+')')
        instance.popup.dismiss()
        self.protocol.sticker_set('song',self.currfile,'rating',instance.rating)

class KmpcApp(App):
    def build_config(self,config):
        config.setdefaults('mpd',{
            'host': '127.0.0.1',
            'port': 6600,
            'basepath': '/mnt/music'
        })
        config.setdefaults('kivy',{
            'log_level': 'info',
            'log_enable': 1,
            'keyboard_mode': 'systemandmulti'
        })
        config.setdefaults('graphics',{
            'width': 800,
            'height': 480
        })
        Config.read(self.get_application_config())
        self.config=config
    def build(self):
        return KmpcInterface(self.config)

if __name__ == '__main__':
    KmpcApp().run()

