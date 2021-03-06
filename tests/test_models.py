import datetime

from mock import patch, Mock
from google.appengine.ext import ndb

from rh.db import *

from tests.dbunit import DatastoreTestCase


class RequestFactoryMixin(object):
    """ Factory methods for tests using request entities """

    def tearDown(self):
        for k in Request.query().fetch(keys_only=True):
            k.delete()

    @staticmethod
    def request(adaptor_name='foo', adaptor_source='bar',
                adaptor_trusted=False,
                content_type=RequestConstants.TRANSCRIBED,
                content_format=RequestConstants.TEXT,
                world=RequestConstants.OFFLINE,
                posted=datetime.datetime(2014, 4, 1),
                processed=datetime.datetime(2014, 4, 1),
                broadcast=False):
        """ Factory method to generate request entities """
        return Request(**locals())

    @staticmethod
    def set_content(request,
                    text_content='We need content',
                    content_language='en',
                    language='fr',
                    topic=RequestConstants.TOPICS[0]):
        """ Set the content for a request """
        kwargs = locals()
        r = kwargs.pop('request')
        r.set_content(**kwargs)
        return r


class RemoteAdaptorTestCase(DatastoreTestCase):
    """ Tests related to RemoteAdaptor model """

    def test_renew_key(self):
        """ A new API key should be added """
        ra = RemoteAdaptor()
        with patch('os.urandom') as urandom:
            urandom.return_value = 'a'
            ra.renew_key()
            self.assertEqual(ra.api_key, 'ra_86f7e437faa5a7fce15d')

    def test_key_renews_on_put(self):
        """ New entities' keys are automatically renewed """
        ra = RemoteAdaptor(name='foo', source='bar', contact='baz')
        with patch('os.urandom') as urandom:
            urandom.return_value = 'a'
            ra.put()
            self.assertEqual(ra.api_key, 'ra_86f7e437faa5a7fce15d')


class RequestTestCase(RequestFactoryMixin, DatastoreTestCase):
    """ Tests methods for fetching requests """

    def test_cds_broadcast_flag(self):
        """ Should fetch entities without broadcast flag """
        # Create test data
        n = 4
        d = [self.request() for i in range(n)]
        d += [self.request(broadcast=True) for i in range(n)]
        ndb.put_multi(d)
        # Test method
        r = Request.fetch_cds_requests()
        self.assertEqual(len(r), n)

    def test_cds_sorting(self):
        """ Should sort reverse chronologically by posted timestamp """
        # Create test data
        d = [self.request(posted=datetime.datetime(2014, 4, i + 1))
             for i in range(4)]
        ndb.put_multi(d)
        # Test method
        r = Request.fetch_cds_requests()
        self.assertEqual(r[0].posted.day, 4)
        self.assertEqual(r[1].posted.day, 3)
        self.assertEqual(r[2].posted.day, 2)
        self.assertEqual(r[3].posted.day, 1)

    def test_create_revision(self):
        """ Should add a new revision """
        r = self.request()
        self.set_content(r)
        self.assertEqual(r.current_revision, 0)
        self.assertEqual(r.revisions[0].text_content, 'We need content')

    def test_add_new_revision(self):
        """ Should update current revision and append revision data """
        r = self.request()
        self.set_content(r)
        r.set_content(text_content='foo')
        self.assertEqual(r.current_revision, 1)
        self.assertEqual(r.revisions[1].text_content, 'foo')
        self.assertEqual(r.revisions[1].text_content, r.text_content)

    def test_content_properties(self):
        """ Content properties should be computed from revisions """
        r = self.request()
        self.set_content(r)
        self.assertEqual(r.text_content, 'We need content')
        r.set_content(text_content='foo')
        self.assertEqual(r.text_content, 'foo')

    def test_setting_no_value_uses_original(self):
        """ Should reuse original values for unspecified properties """
        r = self.request()
        self.set_content(r)
        r.set_content(language='pt_BR')
        # These should be reused
        self.assertEqual(r.revisions[1].text_content,
                         r.revisions[0].text_content)
        self.assertEqual(r.revisions[1].content_language,
                         r.revisions[0].content_language)
        self.assertEqual(r.revisions[1].topic,
                         r.revisions[0].topic)
        # These shoould be updated
        self.assertNotEqual(r.revisions[1].language,
                            r.revisions[0].language)

    def test_passing_no_arguments(self):
        """ Setting content with no arguments should be a no-op """
        r = self.request()
        self.set_content(r)
        r.set_content()
        self.assertEqual(r.current_revision, 0)
        self.assertEqual(len(r.revisions), 1)

    def test_get_current_revision(self):
        """ The ``content`` prop should return the current revision """
        r = self.request()
        self.set_content(r)
        r.set_content(text_content='foo')
        self.assertEqual(r.content, r.revisions[1])
        r.current_revision = 0
        self.assertEqual(r.content, r.revisions[0])

    def test_revert(self):
        """ Should revert to previous revision until there are no more """
        r = self.request()
        self.set_content(r)
        r.set_content(text_content='foo')
        r.set_content(language='pt_BR')
        r.revert()
        self.assertEqual(r.current_revision, 1)
        r.revert()
        self.assertEqual(r.current_revision, 0)
        self.assertEqual(len(r.revisions), 3)
        self.assertEqual(r.text_content, 'We need content')
        self.assertEqual(r.language, 'fr')

    def test_get_all_revisions_up_to_current(self):
        """ Should return only revisions up to current """
        r = self.request()
        self.set_content(r)
        r.set_content(text_content='foo')
        r.set_content(text_content='bar')
        self.assertEquals(len(r.active_revisions), 3)
        self.assertEquals(r.active_revisions[2], r.revisions[2])
        r.revert()
        self.assertEquals(len(r.active_revisions), 2)
        self.assertEquals(r.active_revisions[1], r.revisions[1])

    def test_add_content(self):
        r = self.request()
        r.suggest_url(url='http://example.com/')
        self.assertEqual(len(r.content_suggestions), 1)
        self.assertEqual(r.content_suggestions[0].url, 'http://example.com/')

    def test_duplicate_suggestion_raises(self):
        """ Should raise an exception on duplicate suggestion """
        r = self.request()
        r.suggest_url(url='http://example.com/')
        with self.assertRaises(r.DuplicateSuggestionError) as err:
            r.suggest_url(url='http://example.com/')

    def test_suggestion_sets_has_suggestion(self):
        """ Should set has_suggestion flag when new URL is suggested """
        r = self.request()
        self.assertEqual(r.has_suggestions, False)
        r.suggest_url(url='http://example.com/')
        self.assertEqual(r.has_suggestions, True)

    def test_voted_content(self):
        """ Should return highest voted content """
        r = self.request()
        r.suggest_url(url='http://example.com/')
        r.suggest_url(url='http://test.com/')
        r.content_suggestions[0].votes = 1
        r.content_suggestions[1].votes = 2
        self.assertEqual(r.top_suggestion, r.content_suggestions[1])
        r.content_suggestions[0].votes = 3
        self.assertEqual(r.top_suggestion, r.content_suggestions[0])

    def test_suggestion_pool(self):
        """ Should return top-voted content from the unbroadcast requests """
        r1 = self.request()
        r2 = self.request()
        r3 = self.request(broadcast=True)
        for url in ['http://foo.com/', 'http://bar.com/', 'http://baz.com/']:
            for r in [r1, r2, r3]:
                r.suggest_url(url)
        r1.content_suggestions[1].votes = 2
        r2.content_suggestions[0].votes = 2
        r3.content_suggestions[2].votes = 2
        ndb.put_multi([r1, r2, r3])
        pool = Request.fetch_content_pool()
        self.assertEqual(pool, [r1, r2])

    def test_sorted_suggestions(self):
        """ Should return sorted content suggestions """
        r = self.request()
        r.suggest_url('http://foo.com')
        r.suggest_url('http://bar.com')
        r.content_suggestions[0].votes = 1
        r.content_suggestions[1].votes = 2
        self.assertEqual(r.sorted_suggestions[0], r.content_suggestions[1])
        self.assertEqual(r.sorted_suggestions[1], r.content_suggestions[0])

    def test_pool_sorted_by_votes(self):
        """ Sorted suggestions should be sorted """
        r1 = self.request()
        r2 = self.request()
        r3 = self.request(broadcast=True)
        for url in ['http://foo.com/', 'http://bar.com/', 'http://baz.com/']:
            for r in [r1, r2, r3]:
                r.suggest_url(url)
        r1.content_suggestions[1].votes = 2
        r2.content_suggestions[0].votes = 3
        r3.content_suggestions[2].votes = 4
        ndb.put_multi([r1, r2, r3])
        pool = Request.fetch_content_pool()
        self.assertEqual(pool, [r2, r1])


class ContentTestCase(RequestFactoryMixin, DatastoreTestCase):
    """ Tests related to content suggestion model """

    def test_url_quoting(self):
        c = Content(url='http://test.com/')
        self.assertEqual(c.quoted_url, 'http%3A%2F%2Ftest.com%2F')


class HarvestHistoryTestCase(DatastoreTestCase):
    """ Tests related to harvest history data """

    def adaptor(self, name='foo'):
        """ Factory for mock adaptors """
        adp = Mock()
        adp.name = name
        return adp

    @patch('google.appengine.ext.ndb.model.DateTimeProperty._now')
    def test_record_timestamp(self, now):
        """ Should update timestamp on put """
        now.return_value = datetime.datetime(2014, 4, 1)
        a = self.adaptor()
        h = HarvestHistory.record(a)
        self.assertEqual(h.timestamp, now.return_value)

    @patch('google.appengine.ext.ndb.model.DateTimeProperty._now')
    def test_adaptor_name(self, now):
        """ Should use adaptor name as id """
        now.return_value = datetime.datetime(2014, 4, 1)
        a = self.adaptor()
        h = HarvestHistory.record(a)
        self.assertEqual(h.key, ndb.Key('HarvestHistory', a.name))


    @patch('google.appengine.ext.ndb.model.DateTimeProperty._now')
    def test_get_timestamp(self, now):
        """ Should return a timestamp for a given adaptor """
        now.return_value = datetime.datetime(2014, 4, 1)
        a = self.adaptor('bar')
        h = HarvestHistory.record(a)
        t = HarvestHistory.get_timestamp(a)
        self.assertEqual(h.timestamp, t)

    @patch('google.appengine.ext.ndb.model.DateTimeProperty._now')
    def test_get_timestamp_for_nonexistent(self, now):
        """ Should return UTC unix epoch for nonexistent adaptor """
        now.return_value = datetime.datetime(2014, 4, 1)
        t = HarvestHistory.get_timestamp(self.adaptor('baz'))
        self.assertEqual(t, datetime.datetime.utcfromtimestamp(0))


class PlaylistTestcase(RequestFactoryMixin, DatastoreTestCase):
    """ Tests related to Playlist model """

    def test_get_timestamp(self):
        """ Should return a tuple of date and str instances """
        date, timestamp = Playlist.get_current_timestamp()
        self.assertTrue(isinstance(date, datetime.date))
        self.assertTrue(isinstance(timestamp, str))

    @patch('rh.db.Playlist.get_current_timestamp')
    def test_add_to_new_playlist(self, gct):
        gct.return_value = (datetime.date(2014, 4, 1), '20140401')
        r = self.request()
        r.suggest_url('http://test.com/')
        r.put()
        Playlist.add_to_playlist(r)
        p = Playlist.get_by_id('20140401')
        self.assertEqual(p.content[0].url, 'http://test.com/')
        self.assertEqual(p.content[0].request, r.key)

    @patch('rh.db.Playlist.get_current_timestamp')
    def test_add_to_existing_playlist(self, gct):
        gct.return_value = (datetime.date(2014, 4, 2), '20140402')
        p = Playlist(id='20140402', date=datetime.date(2014, 4, 2))
        p.put()
        r = self.request()
        r.suggest_url('http://test.com/')
        r.put()
        Playlist.add_to_playlist(r)
        p = p.key.get()
        self.assertEqual(p.content[0].url, 'http://test.com/')

    @patch('rh.db.Playlist.get_current_timestamp')
    def test_get_current_playlist(self, gct):
        """ Should return a playlist for today's date """
        gct.return_value = (datetime.date(2014, 4, 3), '20140403')
        p = Playlist.get_current()
        self.assertEqual(p.date, datetime.date(2014, 4, 3))
        self.assertEqual(p.key.id(), '20140403')

    @patch('rh.db.Playlist.get_current_timestamp')
    def test_get_current_existing(self, gct):
        gct.return_value = (datetime.date(2014, 4, 4), '20140404')
        p1 = Playlist(date=datetime.date(2014, 4, 4), id='20140404')
        p1.put()
        p2 = Playlist.get_current()
        self.assertEqual(p1, p2)

    @patch('rh.db.Playlist.get_current_timestamp')
    def test_add_to_playlist_sets_broadcast_flag(self, gct):
        """ Should set broadcast flag on added requests """
        gct.return_value = (datetime.date(2014, 4, 5), '20140405')
        r = self.request(broadcast=False)
        r.suggest_url('http://test.com/')
        Playlist.add_to_playlist(r)
        self.assertTrue(r.broadcast)

    def test_cannot_add_broadcast_requests(self):
        """ Should not do anything when request has a broadcast flag """
        r = self.request(broadcast=True)
        Playlist.add_to_playlist(r)
        self.assertFalse(r in Playlist.get_current().content)
