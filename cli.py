#!/usr/bin/env python

# Requires: lxml, bs4, PyExecJS

import cmd, getpass, json, os, re, requests, sys, time
from lxml import html
from bs4 import BeautifulSoup
import execjs

def args( arg ):
    return arg.split()

class Problem( object ):
    def __init__( self, pid, slug, level, desc='', code='', test='' ):
        self.pid = pid
        self.slug = slug
        self.level = level
        self.desc = desc
        self.code = code
        self.test = test

    def __str__( self ):
        return '%3d %s' % ( self.pid, self.slug )

class Result( object ):
    def __init__( self, data ):
        self.success = data.get( 'run_success' )
        self.result = data.get( 'code_answer', [] )
        self.output = data.get( 'code_output', [] )
        self.runtime = data.get( 'status_runtime', "not available" )

    def __str__( self ):
        s  = 'Succeeded\n' if self.success else 'Failed'
        s += '\nResult:\n' + '\n'.join( self.result )
        s += '\n\nOutput:\n' + '\n'.join( self.output ) if self.output else ''
        s += '\n\nTime: ' + self.runtime
        return s

class OJMixin( object ):
    url = 'https://leetcode.com'
    session = requests.session()
    loggedIn = False

    def login( self ):
        url = self.url + '/accounts/login/'
        xpath = "/html/body/div[1]/div[2]/form/input[@name='csrfmiddlewaretoken']/@value"
        username = raw_input( 'Username: ' )
        password = getpass.getpass()

        self.session.cookies.clear()
        self.loggedIn = False

        resp = self.session.get( url )
        csrf = list( set( html.fromstring( resp.text ).xpath( xpath ) ) )[ 0 ]

        headers = { 'referer' : url }
        data = {
            'login': username,
            'password': password,
            'csrfmiddlewaretoken': csrf
        }

        resp = self.session.post( url, data, headers=headers )
        if self.session.cookies.get( 'LEETCODE_SESSION' ):
            print 'Welcome!'
            self.loggedIn = True

    def get_tags( self ):
        url = self.url + '/problems/api/tags/'

        resp = self.session.get( url )

        tags = {}
        for e in json.loads( resp.text ).get( 'topics' ):
            t = e.get( 'slug' )
            ql = e.get( 'questions' )
            tags[ t ] = ql

        return tags

    def get_problems( self ):
        url = self.url + '/api/problems/all/'

        resp = self.session.get( url )

        problems = {}
        for e in json.loads( resp.text ).get( 'stat_status_pairs' ):
            i = e.get( 'stat' ).get( 'question_id' )
            s = e.get( 'stat' ).get( 'question__title_slug' )
            l = e.get( 'difficulty' ).get( 'level' )
            problems[ i ] = Problem( pid=i, slug=s, level=l )

        return problems

    def get_problem( self, slug ):
        url = self.url + '/problems/%s/description/' % slug
        cls = { 'class' : 'question-description' }
        js = r'var pageData =\s*(.*?);'

        resp = self.session.get( url )
        desc = code = test = ''

        soup = BeautifulSoup( resp.text, 'lxml' )
        for e in soup.find_all( 'div', attrs=cls ):
            desc = e.text
            break

        for s in re.findall( js, resp.text, re.DOTALL ):
            v = execjs.eval( s )
            for cs in v.get( 'codeDefinition' ):
                if cs.get( 'text' ) == 'Python':
                    code = cs.get( 'defaultCode' )
            test = v.get( 'sampleTestCase' )
            break

        return ( desc, code, test )

    def check_interp( self, expected ):
        url = self.url + '/submissions/detail/%s/check/' % expected

        while True:
            time.sleep( 1 )
            resp = self.session.get( url )
            data = json.loads( resp.text )
            if data.get( 'state' ) == 'SUCCESS':
                break
            sys.stdout.write( '.' )

        return Result( data )

    def check_solution( self, p, code ):
        url = self.url + '/problems/%s/interpret_solution/' % p.slug
        referer = self.url + '/problems/%s/description/' % p.slug
        headers = {
                'referer' : referer,
                'content-type' : 'application/json',
                'x-csrftoken' : self.session.cookies[ 'csrftoken' ],
                'x-requested-with' : 'XMLHttpRequest',
        }
        data = {
            'judge_type': 'large',
            'lang' : 'python',
            'test_mode' : False,
            'question_id' : str( p.pid ),
            'typed_code' : code,
            'data_input': p.test,
        }

        resp = self.session.post( url, json=data, headers=headers )
        expected = json.loads( resp.text ).get( 'interpret_expected_id' )
        result = self.check_interp( expected )

        return result

class CodeShell( cmd.Cmd, OJMixin ):
    tags, tag, problems, pid = {}, None, {}, None

    @property
    def prompt( self ):
        return self.cwd() + '> '

    def cwd( self ):
        wd = '/'
        if self.tag:
            wd += self.tag
            if self.pid:
                wd += '/%d-%s' % ( self.pid, self.problems[ self.pid ].slug )
        return wd

    def precmd( self, line ):
        return line.lower()

    def do_login( self, unused ):
        self.login()
        self.tags = self.tag = None

    def do_ls( self, _filter ):
        if not self.tags:
            self.tags = self.get_tags()

        if not self.problems:
            self.problems = self.get_problems()

        if not self.tag:
            for t in sorted( self.tags.keys() ):
                print '\t', '%3d' % len( self.tags[ t ] ), t
        elif not self.pid:
            ql = self.tags.get( self.tag )
            for i in sorted( ql ):
                print '\t', self.problems[ i ]
        else:
            p = self.problems[ self.pid ]
            if not p.desc:
                p.desc, p.code, p.test = self.get_problem( p.slug )
            print p.desc

    def complete_cd( self, text, line, start, end ):
        if self.tag:
            keys = [ str( i ) for i in self.tags[ self.tag ] ]
        else:
            keys = self.tags.keys()

        prefix, suffixes = line.split()[ -1 ], []

        for t in sorted( keys ):
            if t.startswith( prefix ):
                i = len( prefix )
                suffixes.append( t[ i: ] )

        return [ text + s for s in suffixes ]

    def do_cd( self, tag ):
        if tag == '..':
            if self.pid:
                self.pid = None
            elif self.tag:
                self.tag = None
        elif tag in self.tags:
            self.tag = tag
        elif tag.isdigit():
            pid = int( tag )
            if pid in self.problems:
                self.pid = pid

    def do_cat( self, unused ):
        test = '/tmp/test.dat'
        self.pad = '/tmp/%d.py' % self.pid

        p = self.problems[ self.pid ]

        if not os.path.isfile( self.pad ):
            with open( self.pad, 'w' ) as f:
                f.write( p.code )

        with open( test, 'w' ) as f:
            f.write( p.test )

        print self.pad

    def do_check( self, unused ):
        p = self.problems.get( self.pid )
        if p:
            with open( self.pad, 'r' ) as f:
                code = f.read()
                result = self.check_solution( p, code )
                print result

    def do_submit( self, unused ):
        todo = """submit
        if pid:
            error = post pads[ pid ] to submit URL
            if error:
                print test case
                print error"""

        print todo

    def do_cheat( self, unused ):
        todo = """cheat
        if pid:
            sl = cheatsheet.get( pid )
            if not sl:
                sl = get cheatsheet <pid> URL
                cheatsheet[ pid ] = sl
            print the best solutions in sl"""

        print todo

    def do_clear( self, unused ):
        print "\033c"

    def do_eof( self, arg ):
        return True

if __name__ == '__main__':
    shell = CodeShell()
    shell.login()
    shell.cmdloop()
