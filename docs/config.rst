.. _config:

##################################
config file ``~/.kmpc/config.ini``
##################################

This file contains several sections, and must be customized for your use. It
will be created with default values the first time ``kmpc`` is run.

[mpd] section
-------------

mpdhost
  Hostname or IP address that mpd is running on.
mpdport
  Port that mpd is running on.

[paths] section
---------------

musicpath
  Path to the folder containing music. This should be the same file tree that
  the mpd server connected above uses. kmpc uses direct file access to pull
  things like album art and extra id3 tags from the files.
fanartpath
  Path to the folder containing fanart. The directory structure for this folder
  is explained in another section.
tmppath
  Where temporary files should be written.

[sync] section
--------------

synchost
  Hostname or IP address of a host to sync with. This is useful if you have a
  main mpd server running at home and want to sync songs/ratings/fanart to your
  car. The ``kmpcmanager`` program is used to manage this synchost.
syncmusicpath
  The path to the music folder on the synchost.
syncfanartpath
  The path to the fanart folder on the synchost.
synctmppath
  Where temporary files should be written on the synchost.

[system] section
----------------

rpienable
  Set this to ``true`` if you are running this on a Pi and want to control
  Pi-specific features, such as the backlight. Set to ``false`` otherwise.
  Defaults to ``false``.
originalyear
  Set this to ``true`` to display an mp3's originalyear tag as well as the
  regular year tag. Defaults to ``true``.
updatecommand
  This is what runs when you press the Update button. Defaults to ``sudo pip
  install -U kmpc``.

[logs] section
--------------

artlog
  Whether to generate a file named ``artlog.txt`` in the config dir that
  contains data about every media file successfully downloaded from fanart.tv.
  Defaults to ``false``.

[fanart] section
----------------

client_key
  Your personal client key for fanart.tv. This is not necessary, but helps them
  out if you use it.

[songratings] section
---------------------

Customize the meaning of 0-10 stars. The defaults are probably good enough, but
feel free to change them to whatever you want. These are the strings that are
shown in the rating popup.

[artblacklist] section
----------------------

This section is not created by default. It allows you to blacklist certain
fanart files from certain artistids in case you don't want them automatically
downloaded. An entry would look like this::

  b38225b8-8e5f-42aa-bcdc-7bae5b5bdab3 = 128387,128388

The key is a MusicBrainz artistid, and the value is a comma-separated list of
FanArt.tv image ids to ignore.
