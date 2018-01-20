# import dependencies
from mpd import MPDProtocol
import os
import traceback
import mutagen
import io
import random
import pickle
from functools import partial
import json
import subprocess
import tempfile
import shutil
import ConfigParser
from pkg_resources import resource_filename

# make sure we are on an updated version of kivy
import kivy
kivy.require('1.10.0')

#install twisted reactor to interface with mpd
from kivy.support import install_twisted_reactor
# this try/catch block is specifically because sphinx docs fail otherwise
try:
    install_twisted_reactor()
except AttributeError:
    pass
from twisted.internet import reactor, protocol, task, defer, threads

# import config and set key values before other imports
from kivy.config import Config
# this try/catch block is specifically because sphinx docs fail otherwise
try:
    Config.set('kivy','log_level','info') # set this to 'debug' to see more verbose debug messages
    Config.set('graphics','width',1280)
    Config.set('graphics','height',720)
    Config.set('kivy','keyboard_mode','system')
except AttributeError:
    pass

# import all the other kivy stuff
from kivy.app import App
from kivy.support import install_twisted_reactor
from kivy.config import Config
from kivy.logger import Logger
from kivy.graphics import Color,Rectangle
from kivy.core.image import Image as CoreImage
from kivy.metrics import Metrics, sp
from kivy.properties import BooleanProperty
from kivy.network.urlrequest import UrlRequest
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
from kivy.uix.behaviors import ButtonBehavior, FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.lang import Builder

# import our local modules
from mpdfactory import MPDClientFactory
from extra import KmpcHelpers

# sets the location of the config folder
configdir = os.path.expanduser('~')+"/.kmpc"

# load the manager.kv file
Builder.load_file(resource_filename(__name__,'resources/manager.kv'))

Helpers=KmpcHelpers()

class ArtistRecycleBoxLayout(FocusBehavior,LayoutSelectionBehavior,RecycleBoxLayout):
    ''' Adds selection and focus behaviour to the view. '''

class ArtistRow(RecycleDataViewBehavior,BoxLayout):
    ''' Add selection support to the Label '''
    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        ''' Catch and handle the view changes '''
        self.index = index
        return super(ArtistRow, self).refresh_view_attrs(
            rv, index, data)

    def on_touch_down(self, touch):
        ''' Add selection on touch down '''
        if super(ArtistRow, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        ''' Respond to the selection of items in the view. '''
        self.selected = is_selected
        if is_selected:
            App.get_running_app().root.selected_row=index

class UneditTextInput(TextInput):
    def insert_text(self, substring, from_undo=False):
        pass

class ManagerInterface(TabbedPanel):

    def __init__(self,config):
        super(self.__class__,self).__init__()
        # pull config into the class
        self.config = config
        # set up mpd connection
        self.factory = MPDClientFactory()
        self.factory.connectionMade = self.mpd_connectionMade
        self.factory.connectionLost = self.mpd_connectionLost
        reactor.connectTCP(self.config.get('mpd','mpdhost'), self.config.getint('mpd','mpdport'), self.factory)
        self.artist_id_hash={}
        self.artist_name_hash={}
        self.media_hash={}
        self.wr_hash={}
        self.totaldone=0
        self.selected_row=None

    def mpd_connectionMade(self,protocol):
        self.protocol = protocol
        Logger.info('Manager: Connected to mpd server host='+self.config.get('mpd','mpdhost')+' port='+self.config.get('mpd','mpdport'))
        self.ids.library_tab.protocol = self.protocol
        self.refresh_artists_from_cache()

    def mpd_connectionLost(self,protocol, reason):
        Logger.warn('Manager: Connection lost: %s' % reason)

    def handle_mpd_error(self,result):
        Logger.error('Manager: MPDIdleHandler Callback error: {}'.format(result))

    def refresh_artists(self):
        self.protocol.list('musicbrainz_artistid').addCallback(self.populate_artists).addErrback(self.handle_mpd_error)

    def populate_artists(self,result):
        Logger.info("Manager: populate_artists")
        self.totaldone=0
        waittime=1
        self.wr_hash={}
        for row in result:
            aids = str(row)
            for aid in aids.split('/'):
                if aid not in self.artist_id_hash and aid not in self.wr_hash and len(aid)>0:
                    Logger.debug("MusicBrainz: scheduling query in "+str(waittime)+" seconds")
                    Clock.schedule_once(partial(self.query_mb,aid),waittime)
                    waittime=waittime+1
                    self.wr_hash[aid]=True

    def query_mb(self,aid,*largs):
        base="http://musicbrainz.org/ws/2/artist/"
        Logger.info("MusicBrainz: querying "+base+aid+"?fmt=json")
        UrlRequest(req_headers={"User-Agent":"kmpc manager/1.0 ( eratosthene@gmail.com )"},url=base+aid+"?fmt=json",on_success=partial(self.handle_mb_query,aid),on_failure=self.handle_mb_error)

    def handle_mb_query(self,aid,req,mbres):
        aname=mbres['name']
        Logger.debug("result from musicbrainz for aid "+aid+": "+aname)
        self.artist_id_hash[aid]=aname
        self.artist_name_hash[aname]=aid
        data = {'artist_id':aid,'artist_name':aname}
        self.ids.artist_tab.rv.data.append(data)
        self.ids.artist_tab.rv.refresh_from_data()
        self.totaldone=self.totaldone+1
        self.ids.status.text=aid+' ('+str(self.totaldone)+')'

    def handle_mb_error(self,req,result):
        Logger.error("MusicBrainz: web service error "+format(result))

    def write_artists_to_cache(self):
        cachefile=open(configdir+'/artist_cache.pkl','w')
        pickle.dump((self.artist_id_hash,self.artist_name_hash,self.media_hash),cachefile,-1)
        cachefile.close()

    def refresh_artists_from_cache(self):
        cachefile=open(configdir+'/artist_cache.pkl','r')
        (self.artist_id_hash,self.artist_name_hash,self.media_hash)=pickle.load(cachefile)
        cachefile.close()
        self.ids.artist_tab.rv.data=[]
        newdata=[]
        for aid,aname in self.artist_id_hash.iteritems():
            try:
                has_artistbackground=self.media_hash[aid]['has_artistbackground']
            except:
                has_artistbackground=False
            try:
                has_logo=self.media_hash[aid]['has_logo']
            except:
                has_logo=False
            try:
                has_badge=self.media_hash[aid]['has_badge']
            except:
                has_badge=False
            datum = {'artist_id':aid,'artist_name':aname,'has_artistbackground':has_artistbackground,'has_logo':has_logo,'has_badge':has_badge}
            newdata.append(datum)
        self.ids.status.text='pulled '+str(len(self.artist_id_hash))+' lines from cache'
        self.ids.artist_tab.rv.data=sorted(newdata,key=lambda k: k['artist_name'])

    def scan_for_media(self,index):
        Logger.info('Manager: scanning '+self.ids.artist_tab.rv.data[index]['artist_id']+'for media')
        fa_path=self.config.get('paths','fanartpath')
        artistbackground_path=os.path.join(fa_path,self.ids.artist_tab.rv.data[index]['artist_id'],'artistbackground')
        logo_path=os.path.join(fa_path,self.ids.artist_tab.rv.data[index]['artist_id'],'logo')
        badge_path=os.path.join(fa_path,self.ids.artist_tab.rv.data[index]['artist_id'],'badge')
        self.ids.artist_tab.rv.data[index]['has_artistbackground']=os.path.isdir(artistbackground_path)
        self.ids.artist_tab.rv.data[index]['has_logo']=os.path.isdir(logo_path)
        self.ids.artist_tab.rv.data[index]['has_badge']=os.path.isdir(badge_path)
        self.media_hash[self.ids.artist_tab.rv.data[index]['artist_id']]={}
        self.media_hash[self.ids.artist_tab.rv.data[index]['artist_id']]['has_artistbackground']=os.path.isdir(artistbackground_path)
        self.media_hash[self.ids.artist_tab.rv.data[index]['artist_id']]['has_logo']=os.path.isdir(logo_path)
        self.media_hash[self.ids.artist_tab.rv.data[index]['artist_id']]['has_badge']=os.path.isdir(badge_path)
        self.ids.artist_tab.rv.refresh_from_data()

    def scan_row_for_media(self):
        if self.selected_row is not None:
            self.scan_for_media(self.selected_row)
        self.write_artists_to_cache()

    def scan_all_for_media(self):
        for idx in range(0,len(self.ids.artist_tab.rv.data)):
            self.scan_for_media(idx)
        self.write_artists_to_cache()

    def trim_image(self,filename,request,result):
        tdir=tempfile.mkdtemp()
        tf1=os.path.join(tdir,'tf1.png')
        print "fixing "+filename
        print "using tfile "+tf1
        subprocess.call(['convert',filename,'-bordercolor','none','-border','10x10',tf1])
        subprocess.call(['convert',tf1,'-trim','+repage',filename])
        shutil.rmtree(tdir)

    def pull_art(self,index):
        Logger.info('Manager: pulling art for '+self.ids.artist_tab.rv.data[index]['artist_id'])
        aid=self.ids.artist_tab.rv.data[index]['artist_id']
        aname=self.ids.artist_tab.rv.data[index]['artist_name']
        fa_path=self.config.get('paths','fanartpath')
        fanart=self.config.get('api','fanarturl')
        api_key=self.config.get('api','api_key')
        print fanart+aid+"?api_key="+api_key
        request = UrlRequest(url=fanart+aid+"?api_key="+api_key,on_success=partial(self.pull_art2,index))

    def pull_art2(self,index,request,result):
        aid=self.ids.artist_tab.rv.data[index]['artist_id']
        aname=self.ids.artist_tab.rv.data[index]['artist_name']
        fa_path=self.config.get('paths','fanartpath')
        fanart=self.config.get('api','fanarturl')
        api_key=self.config.get('api','api_key')
        d=result
        if 'hdmusiclogo' in d or 'artistbackground' in d or 'musiclogo' in d:
            fapath=os.path.join(fa_path,aid)
            lpath=os.path.join(fapath,"logo")
            abpath=os.path.join(fapath,"artistbackground")
            try:
                print "downloading to "+fapath
                os.mkdir(fapath)
                with open(os.path.join(fapath,"__"+aname.replace('/','_')+"__"),'w'):
                    pass
            except OSError:
                pass
            if 'hdmusiclogo' in d:
                try:
                    os.mkdir(lpath)
                except OSError:
                    pass
                for idx,img in enumerate(d['hdmusiclogo']):
                    if not os.path.isfile(os.path.join(lpath,img['id']+'.png')):
                        print "downloading hdmusiclogo "+img['id']
                        fp=os.path.join(lpath,img['id']+'.png')
                        req = UrlRequest(img['url'],on_success=partial(self.trim_image,fp),file_path=fp)
                        adfile=open(configdir+'/artlog.txt','a')
                        adfile.write(os.path.join(lpath,img['id']+'.png')+"\n")
                        adfile.close()
            if 'musiclogo' in d:
                try:
                    os.mkdir(lpath)
                except OSError:
                    pass
                for idx,img in enumerate(d['musiclogo']):
                    if not os.path.isfile(os.path.join(lpath,img['id']+'.png')):
                        print "downloading musiclogo "+img['id']
                        fp=os.path.join(lpath,img['id']+'.png')
                        req = UrlRequest(img['url'],on_success=partial(self.trim_image,fp),file_path=fp)
                        adfile=open(configdir+'/artlog.txt','a')
                        adfile.write(os.path.join(lpath,img['id']+'.png')+"\n")
                        adfile.close()
            if 'artistbackground' in d:
                try:
                    os.mkdir(abpath)
                except OSError:
                    pass
                for idx,img in enumerate(d['artistbackground']):
                    if not os.path.isfile(os.path.join(abpath,img['id']+'.png')):
                        print "downloading artistbackground "+img['id']
                        fp=os.path.join(abpath,img['id']+'.png')
                        req = UrlRequest(img['url'],file_path=fp)
                        adfile=open(configdir+'/artlog.txt','a')
                        adfile.write(os.path.join(abpath,img['id']+'.png')+"\n")
                        adfile.close()

    def pull_art_for_row(self):
        if self.selected_row is not None:
            self.pull_art(self.selected_row)
            self.scan_for_media(self.selected_row)
        self.write_artists_to_cache()

    def pull_art_for_all(self):
        for idx in range(0,len(self.ids.artist_tab.rv.data)):
            datum=self.ids.artist_tab.rv.data[idx]
            try:
                if not datum['has_logo'] and not datum['has_badge'] and not datum['has_artistbackground']:
                    self.pull_art(idx)
                    self.scan_for_media(idx)
            except KeyError:
                pass
        self.write_artists_to_cache()


class ManagerApp(App):
    def build(self):
        config=Helpers.loadconfigfile()
        # setup some variables that interface.kv will use
        # this is necessary to support packaging the app
        self.songratings = Helpers.songratings(config)
        self.normalfont = resource_filename(__name__,'resources/DejaVuSans.ttf')
        self.fontawesomefont = resource_filename(__name__,'resources/FontAwesome.ttf')
        return ManagerInterface(config)

if __name__ == '__main__':
    ManagerApp().run()
