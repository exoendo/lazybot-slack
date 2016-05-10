#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import sys
import json
import time
import signal
import logging
import collections
import praw
from prawoauth2 import PrawOAuth2Mini as pmini
from slackclient import SlackClient

# Random things to remember:
# <@ ... > is the format to get slack to send an @ notification
# Yes brackets matter..
#
# slackclient is 3rd party
# as_user=True means it will post as 'lazybot'
# if this is not enabled, slack makes it appear as 'Bot'
#
# slackclient has some simple methods but they are meh
# sc.api_call is like the catch-all that basically works with
# everything here: https://api.slack.com/methods
#
# This also uses Real Time Messaging API

logging.basicConfig(level=logging.DEBUG)


class lazybot(object):

    def __init__(self, token):
        self.sc = SlackClient(token)
        self.d = {}

        try:
            self.sc.rtm_connect()
            print 'Connection Successful'
        except Exception as e:
            print str(e)
            exit()

        # the chat stream does not provide usernames with messages,
        # only ID's. So we are building a dictionary of all corresponding
        # IDs and matching them with their usernames, to refer to later
        json_data = self.sc.api_call("users.list")
        parse = json.loads(json_data)

        for info in parse['members']:  # maps slack ID's to usernames
            self.d[info['id']] = info['name']

    def reddit_connect(self, sub):
        ''' Connects to Reddit API '''

        agent = 'Fetching mod-related info for Slack v 2.0.b /u/exoendo'
        self.r = praw.Reddit(user_agent=agent)

        scope_list = ['read', 'modlog', 'privatemessages', 'submit']

        try:
            self.oauth = pmini(self.r, app_key=os.environ['app_key'],
                               app_secret=os.environ['app_secret'],
                               access_token=os.environ['access_token'],
                               refresh_token=os.environ['refresh_token'],
                               scopes=scope_list)
            if self.oauth:
                print '\n\n-->ouath successful\n\n'
            else:
                print '\n\n-->oauth failed\n\n'

        except Exception as e:
            print str(e)
            print 'ouath Failed'
            exit()

        self.subreddit = self.r.get_subreddit(sub)

    def actions(self, data):
        ''' Fetches relevant modlog actions made on a link in last 25 hours '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text='(One moment...)')

        link = data[0]['text'].split('~actions')[1]

        if re.search(r'/comments/\w+/', link):
            link_id = link.split('comments/')[1][:6]
        elif re.search(r'redd\.it/\w+', link):
            link_id = link.split('.it/')[1][:6]
        else:
            msg = '<@{}>: You provided an invalid link...'.format(ping_name)
            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)
            return

        now = time.time()
        msg = ('<@{}>: Actions over last 25 hours '
               '(earliest first): '.format(ping_name))
        action_list = []

        for item in self.subreddit.get_mod_log(limit=None):
            time_diff = now - item.created_utc

            if time_diff / 3600 > 25:
                break
            if item.target_fullname is None:
                continue
            if item.target_fullname[3:] == link_id:
                if item.action != 'removelink' and item.action != 'approvelink':
                    continue
                mod_name = u'{}\u200B{}'.format(item.mod[0], item.mod[1:])
                mod_name = mod_name.encode('utf-8', 'ignore')
                entry = '*{}:* {} | '.format(mod_name, item.action)
                action_list.append(entry)

        if len(action_list) > 0:
            action_list.reverse()
            for item in action_list:
                msg += item
            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)
        else:
            msg = ('<@{}>: No actions have been performed on this '
                   'submission in the last 25 hours '
                   '(or at all...)'.format(ping_name))

            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)

    def handle(self, signum, frame):
        ''' This is for the abrupt heroku SIGTERMS '''

        chan = data[0]['channel']
        msg = 'Lazybot needs to restart. Will be back in a few moments'
        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text=msg)
        sys.exit(0)

    def modlog(self, data):
        ''' Gets Moderator Log actions for the last 1-168 hours '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text='(One moment...)')
        d_temp = {}

        ignore_list = ['AutoModerator', 'PoliticsModeratorBot']

        # split at modlog convert number to int
        hours = int(data[0]['text'].split('~modlog')[1])

        if hours > 168:
            msg = '<@{}>: lazybot caps at 168 hours :)'.format(ping_name)
            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)
            return

        now = time.time()
        for item in self.subreddit.get_mod_log(limit=None):
            result = now - item.created_utc
            if result / 3600 > hours:
                break
            modname = item.mod
            if modname in d_temp:
                d_temp[modname] += 1
            else:
                d_temp[modname] = 1
        msg = '<@{}>: Mod log actions in last {} hour(s): '.format(
            ping_name, hours)

        for info in collections.Counter(d_temp).most_common():
            if info[0] in ignore_list:
                continue
            # We are inserting a zero-width space so no one in chan is pinged
            # Info[0][0] = first letter, \u200B = Space, info[0][1:] = the rest
            name = u'{}\u200B{}'.format(info[0][0], info[0][1:])
            name = name.encode('utf-8', 'ignore')
            msg += '*{}*: {} | '.format(name, info[1])
        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text=msg)

    def modmail(self, data):
        ''' Parses Modmail when link is given '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        mail_msg = data[0]['text'].split('~modmail')[1]
        if len(mail_msg) > 1000:
            msg = '<@{}>: Too Long! lazybot caps modmail messages at 1k chars.'
            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)

            return

        # for finding the msg we sent to reply with a link:
        key_msg = mail_msg[:25]
        title = '{} writes via Slack:'.format(ping_name)

        try:
            self.r.send_message(self.subreddit, title, mail_msg)
            gen = self.r.get_mod_mail(subreddit=self.subreddit, limit=3)
            for item in gen:
                if re.search(key_msg, item.body):
                    link = 'http://www.reddit.com/message/messages/{}'.format(
                        item.id)
                    break
                else:
                    link = '(Failed to return Link...)'
            msg = '<@{}>: Message Sent! {}'.format(ping_name, link)
            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)

        except Exception as e:
            msg = ('Failed to send modmail for some reason.'
                   'If you tell exo he will beat me =(')

            self.sc.api_call('chat.postMessage', as_user=True,
                             channel=chan, text=msg)

    def modque(self, data):
        ''' Fetches the count for unmoderated '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text='(One moment...)')

        posts = 0
        comments = 0
        for item in self.subreddit.get_mod_queue(limit=None):

            if hasattr(item, '_submission'):
                comments += 1
            else:
                posts += 1

        raw_count = comments + posts

        msg = ('<@{}>: *Modqueue Status:*\n*Total Items:* {}\n'
               '*Reported Comments:* {}\n*Reported Posts:* {}\n'
               'https://www.reddit.com/r/politics/about/modqueue/').format(
            ping_name, raw_count, comments, posts)

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text=msg)

    def stickies(self, data):
        ''' Fetches the current sticky threads on subreddit '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text='(One moment...)')

        msg = '<@{}> - Current Active Sticky Threads:'.format(
            ping_name)

        for item in self.subreddit.get_hot(limit=5):
            if not item.stickied:
                continue
            msg += ' {} |'.format(item.short_link)

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text=msg)

    def unmod(self, data):
        ''' Fetches the count for unmoderated '''

        user_id = data[0]['user']
        ping_name = self.d[user_id]
        chan = data[0]['channel']

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text='(One moment...)')

        count = 0
        for item in self.subreddit.get_unmoderated(limit=None):
            count += 1
        msg = ('<@{}>: There are currently {} items in the unmodqueue\n'
               'https://www.reddit.com/r/politics/about/unmoderated/').format(
            ping_name, count)

        self.sc.api_call('chat.postMessage', as_user=True,
                         channel=chan, text=msg)

    def run(self):
        #  signal.signal(signal.SIGTERM, self.handle)

        while True:
            self.oauth.refresh()
            data = self.sc.rtm_read()

            if not data:
                continue
            elif data[0]['type'] != 'message':
                continue
            elif 'text' not in data[0]:
                continue
            print data
            chan = data[0]['channel']

            try:

                if re.match(r'~unmod', data[0]['text']):
                    self.unmod(data)

                elif re.match(r'~modlog \d+$', data[0]['text']):
                    self.modlog(data)

                elif re.match(r'~modque', data[0]['text']):
                    self.modque(data)

                elif re.match(r'~modmail', data[0]['text']):
                    self.modmail(data)

                elif re.match(r'~actions', data[0]['text']):
                    self.actions(data)

                elif re.match(r'~stickies', data[0]['text']):
                    self.stickies(data)

                time.sleep(1)

            except praw.errors.OAuthInvalidToken:
                print 'invalid token'
                if self.oauth.refresh():
                    print '\n\nrefreshed...\n\n'
                else:
                    msg = 'Problem authenticating with Reddit...'
                    self.sc.api_call('chat.postMessage', as_user=True,
                                     channel=chan, text=msg)

            except KeyError:
                pass

if __name__ == "__main__":
    l = lazybot(os.environ['slack_token'])
    l.reddit_connect('politics')
    l.run()
