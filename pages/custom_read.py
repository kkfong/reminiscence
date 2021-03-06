"""
Copyright (C) 2018 kanishka-linux kanishka.linux@gmail.com

This file is part of Reminiscence.

Reminiscence is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Reminiscence is distributed in the hope that it will be useful, 
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with Reminiscence.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
import re
import logging
import hashlib
from urllib.parse import urlparse
from mimetypes import guess_type

from django.http import HttpResponse, FileResponse
from django.conf import settings
from django.urls import reverse
from vinanti import Vinanti
from bs4 import BeautifulSoup
from readability import Document
from .models import Library
from .dbaccess import DBAccess as dbxs

logger = logging.getLogger(__name__)


class CustomRead:
    
    readable_format = [
        'text/plain', 'text/html', 'text/htm',
        'text/css', 'application/xhtml+xml',
        'application/xml', 'application/json',
    ]
    mtype_list = [
        'text/htm', 'text/html', 'text/plain'
    ]
    vnt_noblock = Vinanti(block=False, hdrs={'User-Agent':settings.USER_AGENT},
                  backend=settings.VINANTI_BACKEND,
                  max_requests=settings.VINANTI_MAX_REQUESTS)
    vnt = Vinanti(block=True, hdrs={'User-Agent':settings.USER_AGENT})
    fav_path = settings.FAVICONS_STATIC
    
    @classmethod
    def get_archived_file(cls, url_id, mode='html'):
        qset = Library.objects.filter(id=url_id)
        if qset:
            row = qset[0]
            media_path = row.media_path
            if mode in ['pdf', 'png'] and media_path:
                fln, ext = media_path.rsplit('.', 1)
                if mode == 'pdf':
                    media_path = fln + '.pdf'
                elif mode == 'png':
                    media_path = fln + '.png'
            if media_path and os.path.exists(media_path):
                mtype = guess_type(media_path)[0]
                if not mtype:
                    mtype = 'application/octet-stream'
                ext = media_path.rsplit('.')[-1]
                if ext:
                    filename = row.title + '.' + ext
                    if '.' in row.title:
                        file_ext = row.title.rsplit('.', 1)[-1]
                        if ext == file_ext:
                            filename = row.title
                else:
                    filename = row.title + '.bin'
                if mtype in ['text/html', 'text/htm']:
                    data = cls.format_html(row, media_path)
                    return HttpResponse(data)
                else:
                    response = FileResponse(open(media_path, 'rb'))
                    response['mimetype'] = mtype
                    response['content-type'] = mtype
                    response['content-length'] = os.stat(media_path).st_size
                    filename = filename.replace(' ', '.')
                    print(filename, mtype)
                    if not cls.is_human_readable(mtype):
                        response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
                    return response
            else:
                return HttpResponse('<html>File has not been archived in this format</html>')
        else:
            return HttpResponse('<html>No url exists for this query</html>')
    
    @classmethod
    def read_customized(cls, url_id):
        qlist = Library.objects.filter(id=url_id).select_related()
        data = b"<html>Not Available</html>"
        mtype = 'text/html'
        if qlist:
            row = qlist[0]
            media_path = row.media_path
            if media_path and os.path.exists(media_path):
                mtype = guess_type(media_path)[0]
                
                if mtype in cls.mtype_list:
                    data = cls.format_html(row, media_path,
                                           custom_html=True)
                    if mtype == 'text/plain':
                        mtype = 'text/html'
            elif row.url:
                data = cls.get_content(row, url_id, media_path)
        response = HttpResponse()
        response['mimetype'] = mtype
        response['content-type'] = mtype
        response.write(data)
        return response
    
    @classmethod
    def get_content(cls, row, url_id, media_path):
        data = ""
        req = cls.vnt.get(row.url)
        media_path_parent, _ = os.path.split(media_path)
        if not os.path.exists(media_path_parent):
            os.makedirs(media_path_parent)
        if req and req.content_type and req.html:
            mtype = req.content_type.split(';')[0].strip()
            if mtype in cls.mtype_list:
                content = req.html
                with open(media_path, 'w') as fd:
                    fd.write(content)
                data = cls.format_html(
                    row, media_path, content=content,
                    custom_html=True
                )
                fav_nam = str(url_id) + '.ico'
                final_favicon_path = os.path.join(cls.fav_path, fav_nam)
                if not os.path.exists(final_favicon_path):
                    cls.get_favicon_link(req.html, row.url,
                                         final_favicon_path)
        return data
                    
    @classmethod
    def format_html(cls, row, media_path, content=None, custom_html=False):
        media_dir, file_path = os.path.split(media_path)
        resource_dir = os.path.join(settings.ARCHIVE_LOCATION, 'resources', str(row.id))
        resource_link = '/{}/{}/{}/{}'.format(row.usr.username, row.directory, str(row.id), 'resources')
        if not os.path.exists(resource_dir):
            os.makedirs(resource_dir)
        if not content:
            content = ""
            with open(media_path, encoding='utf-8', mode='r') as fd:
                content = fd.read()
        soup = BeautifulSoup(content, 'lxml')
        for script in soup.find_all('script'):
            script.decompose()
        url_path = row.url
        ourl = urlparse(url_path)
        ourld = ourl.scheme + '://' + ourl.netloc
        link_list = soup.find_all(['a', 'link', 'img'])
        for link in link_list:
            if link.name == 'img':
                lnk = link.get('src', '')
            else:
                lnk = link.get('href', '')
            if lnk and lnk != '#':
                if link.name == 'img' or (link.name == 'link' and '.css' in lnk):
                    lnk = dbxs.format_link(lnk, url_path)
                    lnk_bytes = bytes(lnk, 'utf-8')
                    h = hashlib.sha256(lnk_bytes)
                    lnk_hash = h.hexdigest()
                    if link.name == 'img':
                        link['src'] = resource_link + '/' + lnk_hash
                        if custom_html:
                            link['class'] = 'card-img-top'
                    else:
                        lnk_hash = lnk_hash + '.css'
                        link['href'] = resource_link + '/' + lnk_hash
                    file_image = os.path.join(resource_dir, lnk_hash)
                    if not os.path.exists(file_image):
                        cls.vnt_noblock.get(lnk, out=file_image)
                        logger.info('getting file: {}, out: {}'.format(lnk, file_image))
                elif lnk.startswith('http'):
                    pass
                else:
                    nlnk = dbxs.format_link(lnk, url_path)
                    if link.name == 'img':
                        link['src'] = nlnk
                        if custom_html:
                            link['class'] = 'card-img-top'
                    else:
                        link['href'] = nlnk
        if custom_html:
            ndata = soup.prettify()
            if soup.title:
                title = soup.title.text
            else:
                title = row.url.rsplit('/')[-1]
            data = Document(ndata)
            data_sum = data.summary()
            if data_sum:
                nsoup = BeautifulSoup(data_sum, 'lxml')
                if nsoup.text.strip():
                    data = cls.custom_template(title, nsoup.prettify(), row)
                else:
                    data = cls.custom_soup(ndata, title, row)
            else:
                data = cls.custom_soup(ndata, title, row)
        else:
            data = soup.prettify()
        return bytes(data, 'utf-8')
        
    @staticmethod
    def custom_template(title, content, row):
        if row:
            base_dir = '/{}/{}/{}'.format(row.usr.username, row.directory, row.id)
            read_url = base_dir + '/read'
            read_pdf = base_dir + '/read-pdf'
            read_png = base_dir + '/read-png'
            read_html = base_dir + '/read-html'
        else:
            read_url = read_pdf = read_png = read_html = '#'
            
        template = """
        <html>
            <head>
                <meta charset="utf-8">
                <title>{title}</title>
                <link rel="stylesheet" href="/static/css/bootstrap.min.css">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <meta name="referrer" content="no-referrer">
            </head>
        <body>
            <div class="container-fluid">
                <div class="row">
                    <div class="col-sm"></div>
                    <div class="col-sm">
                        <div class='card text-left bg-light mb-3'>
                            <div class='card-header'>
                                <ul class="nav nav-tabs card-header-tabs">
                                    <li class="nav-item">
                                        <a class="nav-link active" href="{read_url}">HTML</a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" href="{read_html}">Original</a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" href="{read_pdf}">PDF</a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" href="{read_png}">PNG</a>
                                    </li>
                                </ul>
                            </div>
                            <div class='card-body'>
                                <h5 class="card-title">{title}</h5>
                                {content}
                            </div>
                        </div>
                    </div>
                    <div class="col-sm"></div>
                </div>
            </div>
        </body>
        </html>
        """.format(title=title, content=content,
                   read_url=read_url, read_pdf=read_pdf,
                   read_png=read_png, read_html=read_html)
        return template

    @classmethod
    def custom_soup(cls, data, title, row=None):
        soup = BeautifulSoup(data, 'lxml')
        text_result = soup.find_all(text=True)
        final_result = []
        for elm in text_result:
            ntag = ''
            ptag = elm.parent.name
            if ptag == 'a':
                href = elm.parent.get('href')
                ntag = '<a href="{}">{}</a>'.format(href, elm)
            elif ptag in ['body', 'html', '[document]', 'img']:
                pass
            elif ptag == 'p':
                ntag = '<p class="card-text">{}</p>'.format(elm)
            elif ptag == 'span':
                ntag = '<span class="card-text">{}</span>'.format(elm)
            elif '\n' in elm:
                ntag = '</br>';
            else:
                tag = elm.parent.name
                ntag = '<{tag}>{text}</{tag}>'.format(tag=tag, text=elm)
            if ntag:
                final_result.append(ntag)
        result = ''.join(final_result)
        result = re.sub(r'(</br>)+', '', result)
        content = cls.custom_template(title, result, row)
        return content
    
    @classmethod
    def get_favicon_link(cls, data, url_name, final_favicon_path):
        soup = BeautifulSoup(data, 'lxml')
        favicon_link = ''
        if not os.path.exists(final_favicon_path):
            links = soup.find_all('link')
            ilink = soup.find('link', {'rel':'icon'})
            slink = soup.find('link', {'rel':'shortcut icon'})
            if ilink:
                favicon_link = dbxs.format_link(ilink.get('href'), url_name)
            elif slink:
                favicon_link = dbxs.format_link(slink.get('href'), url_name)
            else:
                for i in links:
                    rel = i.get('href')
                    if (rel and (rel.endswith('.ico') or '.ico' in rel)):
                        favicon_link = dbxs.format_link(rel, url_name)
                if not favicon_link:
                    urlp = urlparse(url_name)
                    favicon_link = urlp.scheme + '://' + urlp.netloc + '/favicon.ico'
            if favicon_link:
                cls.vnt_noblock.get(favicon_link, out=final_favicon_path)
    
    @classmethod
    def is_human_readable(cls, mtype):
        human_readable = False
        if mtype in cls.readable_format:
            human_readable = True
        return human_readable
