import os
import codecs
import requests
import re
import yaml
import html2text
import json
from decouple import config
from pprint import pprint
from bs4 import BeautifulSoup as bs
from urllib.parse import urlsplit, urlunsplit
import html

from datetime import datetime

# config is fetched from ".env" file in working directory
API_KEY = config('HELPSCOUT_API_KEY')
COLLECTION_ID = config('COLLECTION_ID')
COLLECTION_URL_BASE = config('COLLECTION_URL_BASE')


class HelpScout(object):
    def __init__(self, api_key):
        self.s = requests.Session()
        self.s.auth = (api_key, 'x')
        self._collections = None
        self._categories = None

    @property
    def collections(self):
        if self._collections is None:
            # TODO: support pagination?
            response = self.s.get('https://docsapi.helpscout.net/v1/collections')
            self._collections = {}
            for collection in  response.json()['collections']['items']:
                self._collections[collection['id']] = collection

        return self._collections

    @property
    def categories(self):
        if self._categories is None:
            self._categories = {}
            for collection in self.collections.keys():
                url = 'https://docsapi.helpscout.net/v1/collections/{id}/categories'.format(id=collection)
                categories = self.s.get(url).json()['categories']['items']
                for category in categories:
                    self._categories[category['id']] = category

        return self._categories

    def get_category_slug_by_id(self, id):
        if self.categories:
            return self.categories[id]['slug']
        else:
            return None

    def get_category_name_by_id(self, id):
        if self.categories:
            return self.categories[id]['name']
        else:
            return None


    def get_collection_articles(self, collection_id, status='published'):
        params = {
            'pageSize': 100, 
            'status': status,
        }
        url = 'https://docsapi.helpscout.net/v1/collections/{id}/articles'.format(id=collection_id)
        response = self.s.get(url, params=params)
        if response.json()['articles']['pages'] > 1:
            i = 2
            items = response.json()['articles']['items']
            while i < response.json()['articles']['pages'] + 1:
                params = {
                    'pageSize': 100, 
                    'status': status,
                    'page': i
                }
                response = self.s.get(url, params=params)
                items = items + response.json()['articles']['items']
                i += 1
            return items
        else:
          response = self.s.get(url, params=params)
          return response.json()['articles']['items']

    def get_article(self, article_id):
        url = 'https://docsapi.helpscout.net/v1/articles/{id}'.format(id=article_id)
        response = self.s.get(url)
        article = response.json().get('article')
        if article is None:
            print(response.status_code)
            print(response.json())
        article['collection'] = self.collections[article['collectionId']]
        catslugs = []
        catnames = []
        for catid in article['categories']:
            catslugs.append( self.get_category_slug_by_id(catid) )
            catnames.append( self.get_category_name_by_id(catid) )

        article['categories'] = catslugs
        article['categories_by_name'] = catnames
        article['tags'] = ['docs']

        return article


def metadata_to_frontmatter(metadata):
    frontmatter = '---\n{yaml}---\n'.format(yaml=yaml.safe_dump(metadata, default_flow_style=False))
    return frontmatter


def html_to_markdown(html):
    h = html2text.HTML2Text()
    return h.handle(html)

def article_to_metadata(article):
    safe_keywords = None
    try:
        #print(article['keywords'])
        safe_keywords = article['keywords']
    except KeyError:
        safe_keywords = '[]'
        print("Key error found for article ", article['publicUrl'])
    
    metadata = {
        'collection': article['collection']['slug'],
        'categories': list(article['categories']),
        'helpscout_url': article['publicUrl'],
        'keywords': safe_keywords,
        'name': article['name'],
        'slug': article['slug'],
    }

    return metadata

def article_to_metadata_hugo(article):
    safe_keywords = None
    try:
        #print(article['keywords'])
        safe_keywords = article['keywords']
    except KeyError:
        safe_keywords = '[]'
        print("Key error found for article ", article['publicUrl'])
    
    #TODO assemble & tidy any hugo-specific FM fields here:

    # lastPublishedAt = '2021-03-10T15:43:15Z' -> parse datetime,
    # convert to date only & don't convert to string
    INPUT_DATE_FORMAT="%Y-%m-%dT%H:%M:%SZ"

    hugo_lastPublishedAt = datetime.strptime(article['lastPublishedAt'], INPUT_DATE_FORMAT)
    hugo_categories = list(article['categories_by_name'])
    hugo_tags = article['tags'] + safe_keywords

    metadata = {
        'collection': article['collection']['slug'],
        'categories': hugo_categories,
        'date': hugo_lastPublishedAt,
        'description': article['name'],
        'helpscout_url': article['publicUrl'],
        'slug': article['slug'],
        'tags': hugo_tags,
        'title': article['name'],

    }

    return metadata

def find_links_in_text(text):
    # Given a chunk of text, find local links
    soup = bs(text, features="html.parser")

    for link in soup.findAll('a'):
        href=link.get('href')
        #if it's a "local" link, strip off the base url and number, leaving the slug

        if href is not None:

            split_href = urlsplit(href)
            regex = ""
            if split_href.netloc == (COLLECTION_URL_BASE) \
                or re.match('^\s*[0-9]*-[a-zA-Z]*',href):
                # absolute link to local resource
                
                newlink="#undefined"
                #strip the URL down to just the slug (without the preceding "NNNN-")
                if split_href.path.startswith("/category/"):
                    restype = "CATEGORY"
                    newlink = re.sub('/category/\d+-', '', split_href.path)
                elif split_href.path.startswith("/article/"):
                    restype="ARTICLE"
                    newlink = re.sub('/article/\d+-', '', split_href.path)
                else:
                    restype="UNKNOWN TYPE"
                    newlink = re.sub('^\d+-', '', split_href.path)
                print("link to local ",restype, href)  

                link['href'] = newlink

            elif href.startswith("/"):
                # relative link to local resource
                #print("relative link to local resource", href)
                # ACTION: locate manually & remove "/"
                ...

            elif href.startswith("#"):
                # in-page link to local resource
                #print("in-page link: ", href)
                # ACTION: leave in place
                ...

            elif href.startswith("http"):
                # other link
                #print("Other external link: ", href)
                # ACTION: leave in place
                ...

            elif href.startswith("mailto:"):
                #print("Mailto link: ", href)
                # ACTION: leave in place
                ...

            else:
                print("Other link: ", href)
                # ACTION: leave in place
                ...
    return str(soup)        
            

def markdown_from_article(article):
    body = html_to_markdown(article['text'])
    metadata = article_to_metadata(article)

    return f'{metadata}\n{body}\n'
    # return metadata_to_frontmatter(metadata) + body

def markdown_hugo_from_article(article):
    print("\n*** Processing ", article['slug'])
    newtext = find_links_in_text(article['text'])
    try:
        body = html_to_markdown(newtext)
    except:
        body = html_to_markdown(article['text'])
        print("failed converting ", article['slug'])
        print( article['text'] )
    metadata = metadata_to_frontmatter(article_to_metadata_hugo(article))

    return f'{metadata}\n{body}\n'

def check_category_dir(slug, name):
    path = 'articles/{}'.format(name)
    if not os.path.exists(path):
        try:
            os.mkdir(path)
        except OSError:
            # directory exists. I hope. should probably check for explict error code
            pass
    index_file_path = os.path.join(path, "_index.md")
    if not os.path.exists(index_file_path):
        metadata = {
            'description': "Articles about X",
            'title': name,
            'linkTitle': name,
            'weight': 1,
            'tags': ["docs"]
        }
        metadata_fm = metadata_to_frontmatter(metadata)
        with codecs.open(index_file_path, "w", "utf-8") as f:
            f.write(metadata_fm)
            print("\nwrote index file WITH CHILDREN: ", index_file_path)

def write_article(article, article_format):
    path = 'articles/{}'.format(article['collection']['slug'])

    if article_format == "markdown":
        filename = '{}/{}.md'.format(path, article['slug'])
    elif article_format == "markdown_hugo":
        primary_category = article['categories'][0]
        primary_category_name = article['categories_by_name'][0]
        path = 'articles/{}'.format(primary_category_name)
        # check category directory exists and has _index.md file
        check_category_dir(primary_category, primary_category_name)
        filename = '{}/{}.md'.format(path, article['slug'])
    elif article_format == "html":
        filename = '{}/{}.html'.format(path, article['slug'])
    elif article_format == "json":
        filename = '{}/{}.json'.format(path, article['slug'])
    
    filename_meta = '{}/metadata.json'.format(path, article['slug'])

    if not os.path.exists(path):
        try:
            os.mkdir(path)
        except OSError:
            # directory exists. I hope. should probably check for explict error code
            pass

    with codecs.open(filename, "w", "utf-8") as f:
        if article_format == "markdown":
            f.write(markdown_from_article(article))
        elif article_format == "markdown_hugo":
            f.write(markdown_hugo_from_article(article))
        elif article_format == "html":
            f.write(article['text'])
        elif article_format == "json":
            metadata = article_to_metadata(article)
            metadata['content'] = article['text']
            json.dump(metadata, f, ensure_ascii=False, indent=4)


def export(h):
    if not os.path.exists('articles'):
        try:
            os.mkdir('articles')
        except OSError:
            # directory exists. I hope. should probably check for explict error code
            pass

    for collection in h.collections.keys():
        if collection == COLLECTION_ID:
            articles = h.get_collection_articles(collection)
            for article_id in map(lambda a: a['id'], articles):
                article = h.get_article(article_id)
                #print(article['slug'])
                # write_article(article, "html")
                # write_article(article, "mardown")
                #write_article(article, "json")
                write_article(article, "markdown_hugo")


def export_metadata(h):
    with codecs.open('articles/collections.json', 'w', 'utf-8') as f:
        json.dump(h.collections, f, ensure_ascii=False, indent=4)

    with codecs.open('articles/categories.json', 'w', 'utf-8') as f:
        json.dump(h.categories, f, ensure_ascii=False, indent=4)


if __name__ == '__main__':
    h = HelpScout(API_KEY)
    export(h)
    export_metadata(h)
