#!/usr/bin/env python

# Basic PALAPA Module
# v.05
# --------
# Initial version, using GeoServer plain password, as GeoServer hash is ... :P
#
# tejo
# August 2016

import sys, os, shutil
# abspath = os.path.dirname(__file__)
# sys.path.append(abspath)
# os.chdir(abspath)
import urllib2, json, base64, sqlalchemy, sqlalchemy_utils, zipfile, ogr, shapefile, psycopg2, uuid, jwt, time, datetime, re
import ogr2ogr, osr, re, gdal, xmltodict, fnmatch
from flask import Flask, abort, request, redirect, jsonify, g, url_for, send_from_directory, Response, stream_with_context
from flask_jwt import JWT, jwt_required, current_identity
from werkzeug import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_security import http_auth_required, auth_token_required, Security, RoleMixin, UserMixin, SQLAlchemyUserDatastore
from sqlalchemy import create_engine
from sqlalchemy.sql import func
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS, cross_origin
from passlib.apps import custom_app_context as pwd_context
from itsdangerous import (TimedJSONWebSignatureSerializer as Serializer, BadSignature, SignatureExpired)
from flask_marshmallow import Marshmallow
from geoserver.catalog import Catalog
from urllib2 import unquote
from owslib.csw import CatalogueServiceWeb
from owslib.wms import WebMapService
from shutil import copyfile
from big_parser import parse_big_md
from pygeometa import render_template
from dbfread import DBF
from datetime import datetime as dt
import StringIO
import proxypy
import cfg

# initialization
app = Flask(__name__)
app.config['APP_BASE'] = cfg.APP_BASE
app.config['SECURITY_TRACKABLE'] = cfg.SECURITY_TRACKABLE
app.config['SECURITY_PASSWORD_HASH'] = cfg.SECURITY_PASSWORD_HASH
app.config['SECURITY_PASSWORD_SALT'] = cfg.SECURITY_PASSWORD_SALT
app.config['WTF_CSRF_ENABLED'] = cfg.WTF_CSRF_ENABLED
app.config['SECURITY_TOKEN_MAX_AGE'] = cfg.SECURITY_TOKEN_MAX_AGE
app.config['SECRET_KEY'] = cfg.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = cfg.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_BINDS'] = cfg.SQLALCHEMY_BINDS
app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN'] = cfg.SQLALCHEMY_COMMIT_ON_TEARDOWN
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = cfg.SQLALCHEMY_TRACK_MODIFICATIONS
app.config['SQLALCHEMY_DATASTORE'] = cfg.SQLALCHEMY_DATASTORE
app.config['GEOSERVER_REST_URL'] = cfg.GEOSERVER_REST_URL
app.config['GEOSERVER_WMS_URL'] = cfg.GEOSERVER_WMS_URL
app.config['GEOSERVER_WFS_URL'] = cfg.GEOSERVER_WFS_URL
app.config['GEOSERVER_USER'] = cfg.GEOSERVER_USER
app.config['GEOSERVER_PASS'] = cfg.GEOSERVER_PASS
app.config['GEOSERVER_THUMBNAILS'] = cfg.GEOSERVER_THUMBNAILS
app.config['GEOSERVER_LAYERS_PROP'] = cfg.GEOSERVER_LAYERS_PROP
app.config['DATASTORE_HOST'] = cfg.DATASTORE_HOST
app.config['DATASTORE_PORT'] = cfg.DATASTORE_PORT
app.config['DATASTORE_USER'] = cfg.DATASTORE_USER
app.config['DATASTORE_PASS'] = cfg.DATASTORE_PASS
app.config['DATASTORE_DB'] = cfg.DATASTORE_DB
app.config['UPLOAD_FOLDER'] = cfg.UPLOAD_FOLDER
app.config['RASTER_FOLDER'] = cfg.RASTER_FOLDER
app.config['RASTER_STORE'] = cfg.RASTER_STORE
app.config['DOCUMENTS_FOLDER'] = cfg.DOCUMENTS_FOLDER
app.config['DOWNLOADS_FOLDER'] = cfg.DOWNLOADS_FOLDER
app.config['ALLOWED_EXTENSIONS'] = cfg.ALLOWED_EXTENSIONS
app.config['ALLOWED_VECTOR'] = cfg.ALLOWED_VECTOR
app.config['ALLOWED_RASTER'] = cfg.ALLOWED_RASTER
app.config['CSW_URL'] = cfg.CSW_URL
app.config['PALAPA_FOLDER'] = cfg.PALAPA_FOLDER

# reload(sys)  
# sys.setdefaultencoding('utf8')

# extensions
db = SQLAlchemy(app)
auth = HTTPBasicAuth()
ma = Marshmallow(app)
CORS(app)

# Functions

# Mengambil data dari Geoserver REST (output JSON)
def georest_get(rest_url, user, password):
    url_get = urllib2.Request(rest_url)
    base64string = base64.encodestring('%s:%s' % (user, password)).replace('\n','')
    url_get.add_header('Content-Type', 'application/json')
    url_get.add_header("Authorization", "Basic %s" % base64string)
    try:
        rest_response = urllib2.urlopen(url_get)
    except urllib2.HTTPError, e:
        if e.code == 401:
            output = '401'
        elif e.code == 404:
            output = '404'
        elif e.code == 503:
            output = '503'
        else:
            output = '999'
    else:
        output = json.loads(rest_response.read())
    return output

def pycsw_get(csw_url, request_param):
    csw_url = csw_url + request_param
    url_get = urllib2.Request(csw_url)
    try:
        pycsw_response = urllib2.urlopen(url_get)
    except urllib2.HTTPError, e:
        if e.code == 401:
            output = '401'
        elif e.code == 404:
            output = '404'
        elif e.code == 503:
            output = '503'
        else:
            output = '999'
    else:
        output = json.loads(pycsw_response.read())
    return output       

# Fungsi pembatasan ekstensi file yang boleh di unggah    
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_EXTENSIONS']

def allowed_vector(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_VECTOR']

def allowed_raster(filename):
    return '.' in filename and filename.rsplit('.',1)[1] in app.config['ALLOWED_RASTER']    

def allowed_sld(filename):
    return '.' in filename and filename.rsplit('.',)[1] in set(['sld', 'SLD'])

def allowed_xml(filename):
    return '.' in filename and filename.rsplit('.',)[1] in set(['xml', 'XML'])

def allowed_docs(filename):
    return '.' in filename and filename.rsplit('.',)[1] in set(['docx', 'DOCX', 'doc', 'DOC', 'txt', 'TXT', 'xlsx', 'XLSX', 'xls', 'XLS', 'pdf', 'PDF'])

def wkt2epsg(wkt, epsg=app.config['APP_BASE'] + 'epsg.txt', forceProj4=False):
    code = None
    p_in = osr.SpatialReference()
    s = p_in.ImportFromWkt(wkt)
    if s == 5:  # invalid WKT
        return None
    if p_in.IsLocal() == 1:  # this is a local definition
        return p_in.ExportToWkt()
    if p_in.IsGeographic() == 1:  # this is a geographic srs
        cstype = 'GEOGCS'
    else:  # this is a projected srs
        cstype = 'PROJCS'
    an = p_in.GetAuthorityName(cstype)
    ac = p_in.GetAuthorityCode(cstype)
    if an is not None and ac is not None:  # return the EPSG code
        return '%s:%s' % \
            (p_in.GetAuthorityName(cstype), p_in.GetAuthorityCode(cstype))
    else:  # try brute force approach by grokking proj epsg definition file
        p_out = p_in.ExportToProj4()
        if p_out:
            if forceProj4 is True:
                return p_out
            f = open(epsg)
            for line in f:
                if line.find(p_out) != -1:
                    m = re.search('<(\\d+)>', line)
                    if m:
                        code = m.group(1)
                        break
            if code:  # match
                return 'EPSG:%s' % code
            else:  # no match
                return None
        else:
            return None

def unzip(source_filename, dest_dir):
    with zipfile.ZipFile(app.config['UPLOAD_FOLDER'] + source_filename) as zf:
        print app.config['UPLOAD_FOLDER'] + source_filename
        for member in zf.infolist():
            # Path traversal defense copied from
            # http://hg.python.org/cpython/file/tip/Lib/http/server.py#l789
            words = member.filename.split('/')
            path = app.config['UPLOAD_FOLDER'] + dest_dir.split('.')[0]   
            print "Path : " + path  
            if not os.path.exists(path):
                os.makedirs(path)
            for word in words[:-1]:
                while True:
                    drive, word = os.path.splitdrive(word)
                    head, word = os.path.split(word)
                    if not drive:
                        break
                if word in (os.curdir, os.pardir, ''):
                    continue
                path = os.path.join(path, word)
            print "Path2 : " + path
            zf.extract(member, path)

def populateORDB(source_shp, database):
    drive = org.GetDriverByName('ESRI Shapesfile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    # engine = create_engine(app.config['SQLALCHEMY_BIND']['dbdev']) 
    pass

def pgis2pgis(source_db, source_schema, source_table, dest_db, dest_schema, dest_table, identifier):
    pg_conn_input =  "PG:host='" + app.config['DATASTORE_HOST'] + "' port='" + app.config['DATASTORE_PORT'] + "' user='" + app.config['DATASTORE_USER'] + "' dbname='" + source_db + "' password='" + app.config['DATASTORE_PASS'] + "'" 
    pg_conn_output =  "PG:host='" + app.config['DATASTORE_HOST'] + "' port='" + app.config['DATASTORE_PORT'] + "' user='" + app.config['DATASTORE_USER'] + "' dbname='" + dest_db + "' password='" + app.config['DATASTORE_PASS'] + "'" 
    fitur_in = source_schema + '.' + source_table
    fitur_out = dest_schema + '.' + dest_table
    schemaout = "SCHEMA='" + dest_schema + "'"
    sql = "SELECT * from " + fitur_in + " WHERE metadata=" + "'" + identifier + "'"
    print "In/Out:", fitur_in, fitur_out
    print "Conn In/Out:", pg_conn_input, pg_conn_output
    print "SQL:", sql
    try:
        # ogr2ogr.main(["-append", "-a_srs", "EPSG:4326", "-f", "PostgreSQL", "--config", "PG_USE_COPY YES", pg_conn_input, pg_conn_output, fitur_in, fitur_out])
        ogr2ogr.main(["", "-f", "PostgreSQL", "-append", "-nln", fitur_out, "-lco", schemaout, pg_conn_output, pg_conn_input, "-sql", sql])
        msg = "Copy Normal!"
    except:
        msg = "Copy gagal!"
    return msg

def populateDB(source_shp, database, kodesimpul):
    # Get Layer EPSG
    print 'Source: ' + source_shp
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    pg_conn = "PG:host=" + app.config['DATASTORE_HOST'] + " port=" + app.config['DATASTORE_PORT'] + " user=" + app.config['DATASTORE_USER'] + " dbname=" + database + " password=" + app.config['DATASTORE_PASS']
    print 'Shape: ' + shape
    # print 'PG: ' + pg_conn
    shape_file = driver.Open(shape)
    # uuided = uuid.uuid4()
    dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    print "DT", dt
    uuided = kodesimpul + str(dt)
    shape_id = source_shp.split('.')[0]+'-'+ str(uuided)
    layer = shape_file.GetLayer()
    crs = layer.GetSpatialRef()
    tipe = 'VECTOR'
    try:
        EPSG = wkt2epsg(crs.ExportToWkt())
        print EPSG
        ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nln", shape_id,"-nlt","PROMOTE_TO_MULTI", "-a_srs",EPSG])
        msg = " Data masuk ke database secara normal!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
    except:
        msg = " Data masuk ke database, namun proyeksi tidak didefinisikan. Memaksakan ke proyeksi EPSG:4326"
        EPSG = "EPSG:4326"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
        ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nln", shape_id,"-nlt","PROMOTE_TO_MULTI", "-a_srs",EPSG])
    # driver.Close(shape)
    # ogr2ogr.main(["","-f", "PostgreSQL", pg_conn, shape,"-nlt","PROMOTE_TO_MULTI"])

def populateKUGI(source_shp, database, schema, table, scale, fcode):
    # Get Layer EPSG
    print 'Source: ' + source_shp
    driver = ogr.GetDriverByName('ESRI Shapefile')
    shape = app.config['UPLOAD_FOLDER'] + source_shp.split('.')[0] +'/'+ source_shp.split('.')[0]+'.shp'
    pg_conn = "PG:host=" + app.config['DATASTORE_HOST'] + " port=" + app.config['DATASTORE_PORT'] + " user=" + app.config['DATASTORE_USER'] + " dbname=" + database + " password=" + app.config['DATASTORE_PASS']
    print 'Shape: ' + shape
    print 'PG: ' + pg_conn
    shape_file = driver.Open(shape)
    dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    print "DT", dt
    uuided = str(dt)
    shape_id = source_shp.split('.')[0]+'-'+ str(uuided)
    layer = shape_file.GetLayer()
    crs = layer.GetSpatialRef()
    tipe = 'VECTOR'
    fitur = schema + '.' + table
    # fitur = schema + '.' + table + '_' + scale
    print fitur
    sql = "SELECT * from '%s' WHERE FCODE='%s'" % (shape_id, fcode)
    print sql
    
    # where = "FCODE=\"%s\"" % (fcode)

    where = "FCODE='" + fcode + "'"

    print where

    EPSG = wkt2epsg(crs.ExportToWkt())

    print "[ " + "", "-append","-f", "PostgreSQL", pg_conn, shape,"-nln", fitur,"-nlt","PROMOTE_TO_MULTI", "-a_srs", EPSG, "-where", where + " ]"

    try:
        EPSG = wkt2epsg(crs.ExportToWkt())
        print EPSG
        try:
            ogro = ogr2ogr.main(["", "-append","-f", "PostgreSQL", pg_conn, shape,"-nln", fitur,"-nlt","PROMOTE_TO_MULTI", "-a_srs", EPSG, "-where", where])
            if ogro:
                msg = " Data masuk ke database secara normal!"
            else:
                msg = " Terjadi kegagalan import!"
        except:
            msg = " Terjadi kegagalan import!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe, ogro
    except:
        msg = " Data masuk ke database, namun proyeksi tidak didefinisikan. Memaksakan ke proyeksi EPSG:4326"
        EPSG = "EPSG:4326"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe
        try:
            ogro = ogr2ogr.main(["", "-append","-f", "PostgreSQL", pg_conn, shape,"-nln", fitur,"-nlt","PROMOTE_TO_MULTI", "-a_srs", EPSG, "-where", where])
            if ogro:
                msg = " Data masuk ke database secara normal!"
            else:
                msg = " Terjadi kegagalan import!"
        except:
            msg = " Terjadi kegagalan import!"
        return msg, EPSG, source_shp.split('.')[0], str(uuided), tipe, ogro

def save_table(db, skema, fitur, identifier):
    print db, identifier, skema, fitur
    pg_conn = "PG:host=" + app.config['DATASTORE_HOST'] + " port=" + app.config['DATASTORE_PORT'] + " user=" + app.config['DATASTORE_USER'] + " dbname=" + db + " password=" + app.config['DATASTORE_PASS']
    print pg_conn
    sql = "SELECT * from %s.%s WHERE metadata='%s'" % (skema, fitur, identifier)
    print sql
    try:
        ogro = ogr2ogr.main(["", "-f", "GML", app.config['DOWNLOADS_FOLDER'] + fitur + '_' + identifier + '.gml', pg_conn, "-sql", sql])
        msg = app.config['DOWNLOADS_FOLDER'] + fitur + '_' + identifier + '.gml'
    except:
        msg = " Error"
    return msg

def populateRS(source_ras,kodesimpul):
    print source_ras
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    name = source_ras.split('.')[0]
    dt = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    print "DT", dt
    uuided = kodesimpul + str(dt)
    layer_id = name + '-' + str(uuided)
    layer_file = app.config['RASTER_FOLDER']+layer_id.replace('-','_')+'.tif'
    print layer_file
    copyfile(app.config['UPLOAD_FOLDER']+source_ras+'/'+source_ras+'.tif', layer_file)
    datafile = gdal.Open(layer_file)
    EPSG = wkt2epsg(datafile.GetProjection())
    tipe = 'RASTER'
    msg = " Raster projection: " + EPSG
    print 'Source: ' + source_ras
    return msg, EPSG, layer_id, str(uuided),tipe

def get_iden_unik(filedbf):
    table = DBF(filedbf)
    list_iden = []
    for record in table:
        try:
            list_iden.append(record['METADATA'])
        except:
            list_iden = []
    list_iden_unik = list(set(list_iden))
    return list_iden_unik

def get_srsId(filedbf):
    table = DBF(filedbf)
    srsId = []
    for record in table:
        try:
            srsId.append(record['SRS_ID'])
        except:
            srsId = []
    srsId_unik = list(set(srsId))
    return srsId_unik        

def get_fcode(filedbf):
    table = DBF(filedbf)
    fcode = []
    for record in table:
        try:
            fcode.append(record['FCODE'])
        except:
            fcode = []
    fcode_unik = list(set(fcode))
    return fcode_unik          

def cek_fcode(schema, table):
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    sql = "select split_part(split_part(column_default, '::', 1), '''',2) AS fcode FROM information_schema.COLUMNS WHERE table_schema = '%s' and table_name = '%s' and column_name = 'fcode'" % (str(schema), str(table))
    result = engine.execute(sql)
    try:
        for row in result:
            isi = {}
            print row
    except:
        pass 
    print "CEKFCODE:", str(row[0]) 
    return str(row[0]) 

def refresh_dbmetafieldview(database):
    db = database
    # engine = create_engine(app.config['SQLALCHEMY_BINDS'][database])
    if database == 'dbdev':
        db = 'palapa_dev'
    if database == 'dbprod':
        db = 'palapa_prod'
    if database == 'dbpub':
        db = 'palapa_pub'
    con = psycopg2.connect(dbname=db, user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "SELECT public._a_cekmetadata()"
    cur.execute(sql)
    con.close()
    msg = "Refreshed" 
    # print "DB:", database
    # try:
    #     result = engine.execute(func._a_cekmetadata())
    #     for row in result:
    #         print "RESULT:", row
    #     db.session.commit()
    #     msg = "Refreshed" 
    # except:
    #     msg = "Terjadi kesalahan!"  
    # print msg
    return msg

def delete_spatial_records(skema,fitur,identifier,database):
    db = database
    if database == 'dbdev':
        db = 'palapa_dev'
    if database == 'dbprod':
        db = 'palapa_prod'
    if database == 'dbpub':
        db = 'palapa_pub'
    con = psycopg2.connect(dbname=db, user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "DELETE from %s.%s WHERE metadata='%s';" % (str(skema), str(fitur), str(identifier))    
    print sql
    cur.execute(sql)
    con.close()
    msg = "Deleted" 
    return msg

def delete_metadata(fitur):
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "DELETE from metadata WHERE identifier='%s';" % (str(fitur))    
    print sql
    cur.execute(sql)
    con.close()
    msg = "Deleted" 
    return msg

def delete_metakugi(fitur):
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "DELETE from metakugi WHERE identifier='%s';" % (str(fitur))    
    print sql
    cur.execute(sql)
    con.close()
    msg = "Deleted" 
    return msg

def delete_metakugi_db(db, fitur):
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "DELETE from metakugi_%s WHERE identifier='%s';" % (str(db), str(fitur))    
    print sql
    cur.execute(sql)
    con.close()
    msg = "Deleted" 
    return msg    

def delete_metalinks(fitur):
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql = "DELETE from metalinks WHERE identifier='%s';" % (str(fitur))    
    print sql
    cur.execute(sql)
    con.close()
    msg = "Deleted" 
    return msg    

def get_all(myjson, key):
    if type(myjson) == str:
        myjson = json.loads(myjson)
    if type(myjson) is dict:
        for jsonkey in myjson:
            if type(myjson[jsonkey]) in (list, dict):
                get_all(myjson[jsonkey], key)
            elif jsonkey == key:
                print myjson[jsonkey]
    elif type(myjson) is list:
        for item in myjson:
            if type(item) in (list, dict):
                get_all(item, key)

def get_gs_namespaces():
  matches = []
  namespaces = []
  for root, dirnames, filenames in os.walk(cfg.GEOSERVER_DATA_DIR + 'workspaces'):
    namespace = {}
    for filename in fnmatch.filter(filenames, 'namespace.xml'):
      thefile = os.path.join(root, filename)
      matches.append(thefile)
      with open(thefile) as file:
          xml = file.read()
      content = xmltodict.parse(xml)
      namespace['id'] = content['namespace']['id']
      namespace['name'] = content['namespace']['prefix']
      namespaces.append(namespace)
      namespace = {}
  return namespaces

def get_gs_layers():
  matches = []
  layers = []
  for root, dirnames, filenames in os.walk(cfg.GEOSERVER_DATA_DIR + 'workspaces'):
    layer = {}
    for filename in fnmatch.filter(filenames, 'layer.xml'):
      thefile = os.path.join(root, filename)
      matches.append(thefile)
      with open(thefile) as file:
          xml = file.read()
      content = xmltodict.parse(xml)
      layer['id'] = content['layer']['resource']['id']
      layer['name'] = content['layer']['name']
      layer['type'] = content['layer']['type']
      layer['defaultStyle_id'] = content['layer']['defaultStyle']['id']
      layers.append(layer)
      layer = {}
  return layers

def get_gs_styles():
  matches = []
  styles = []
  for root, dirnames, filenames in os.walk(cfg.GEOSERVER_DATA_DIR + 'styles'):
    style = {}
    for filename in fnmatch.filter(filenames, '*.xml'):
      thefile = os.path.join(root, filename)
      matches.append(thefile)
      with open(thefile) as file:
          xml = file.read()
      content = xmltodict.parse(xml)
      style['id'] = content['style']['id']
      style['name'] = content['style']['name']
      styles.append(style)
      style = {}
  return styles

def str_to_bool(s):
  if s == 'True':
    return True
  elif s == 'False':
    return False

def pycswadv(layer_id,layer_workspace,layer_tipe):
    identifier = layer_id
    workspace = layer_workspace
    tipe = layer_tipe
    if workspace == 'KUGI':
        fi = workspace + ':' + identifier
        xmlmeta = Metakugi.query.filter_by(fitur=identifier).first()
        xml_payload = xmlmeta.xml
        akses = xmlmeta.akses
    else:
        fi = workspace + ':' + identifier
        xmlmeta = Metalinks.query.filter_by(identifier=identifier).first()
        xml_payload = xmlmeta.xml
        akses = xmlmeta.akses
    mcf_template = parse_big_md(xml_payload)
    try:
        print "Identifier:", layer_id
        print "Workspace:", layer_workspace
        print "Akses:", akses
        print fi
        if akses == 'PUBLIC':
            restriction = 'unclassified'
        if akses == 'GOVERNMENT':
            restriction = 'restricted'
        if akses.split(':')[0] == 'GOVERNMENT':
            restriction = 'restricted'
        if akses == 'PRIVATE':
            restriction = 'confendential'
        if akses == 'IGSTRATEGIS':
            restriction = 'topsecret'
        print restriction  
        wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
        print wms
        bbox = wms[fi].boundingBoxWGS84
        wb = str(bbox[0])
        sb = str(bbox[1])
        eb = str(bbox[2])
        nb = str(bbox[3])
        bboxwgs84 = wb+','+sb+','+eb+','+nb
        print bboxwgs84
        wmslink = app.config['GEOSERVER_WMS_URL'] + "service=WMS&version=1.1.0&request=GetMap&layers=" + fi + "&styles=&bbox=" + bboxwgs84 + "&width=768&height=768&srs=EPSG:4326&format=application/openlayers"
        wfslink = app.config['GEOSERVER_WFS_URL'] + "service=WFS&version=1.0.0&request=GetFeature&typeName=" + fi + "&outputFormat=shape-zip"
        print wmslink
        print wfslink
        mcf_template = mcf_template.replace('$$rep:fileIdentifier$$', fi)
        mcf_template = mcf_template.replace('$$rep:security$$', restriction)
        mcf_template = mcf_template.replace('$$rep:secnote$$', akses)
        mcf_template = mcf_template.replace('$$rep:geoserverwms$$', app.config['GEOSERVER_WMS_URL'])
        mcf_template = mcf_template.replace('$$rep:geoserverfullwms$$', wmslink)
        mcf_template = mcf_template.replace('$$rep:geoserverwfs$$', app.config['GEOSERVER_WFS_URL'])
        mcf_template = mcf_template.replace('$$rep:geoserverfullwfs$$', wfslink)
        mcf_template = mcf_template.replace('$$rep:bboxwgs84$$', bboxwgs84)
        rendered_xml = render_template(mcf_template, schema_local=app.config['APP_BASE'] + 'CP-indonesia')
    # print rendered_xml
    except:
        msg = json.dumps({'MSG':'Metadata tidak sesuai standar!'})
    # try:
    # print rendered_xml
    csw = CatalogueServiceWeb(app.config['CSW_URL'])
    cswtrans = csw.transaction(ttype='insert', typename='gmd:MD_Metadata', record=rendered_xml)
    if workspace == 'KUGI':
        metakugi = Metakugi.query.filter_by(fitur=identifier).first()     
        metakugi.published = 'Y'
        db.session.commit()                          
    else:
        metalinks = Metalinks.query.filter_by(identifier=identifier).first()
        metalinks.published = 'Y'
        db.session.commit()
    msg = json.dumps({'MSG':'Publish servis CSW sukses!'})
    return msg

def pycswdel(layer_id, layer_workspace): 
    identifier = layer_id
    workspace = layer_workspace
    try:
        con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()
        if workspace == 'KUGI':
            print "WK KUGI"
            kugi_identifier = "KUGI:" + identifier 
            sql = "DELETE from metadata WHERE identifier='%s';" % (str(kugi_identifier))    
            print sql         
            cur.execute(sql)                
            sqlm = "UPDATE metakugi SET published='N' WHERE fitur='%s';" % (str(identifier))
            cur.execute(sqlm)
        else:
            print "WK OTHERS"
            identifierlink = workspace + ':' + identifier
            sql = "DELETE from metadata WHERE identifier='%s';" % (str(identifierlink))    
            print sql         
            cur.execute(sql)                
            sqlm = "UPDATE metalinks SET published='N' WHERE identifier='%s';" % (str(identifier))
            cur.execute(sqlm)                
        msg = json.dumps({'MSG':'Berhasil unpublish servis CSW!'})
    except:
        msg = json.dumps({'MSG':'Gagal unpublish servis CSW!'})
    return msg

# Database
class User(db.Model):
    __tablename__ = 'users'
    #id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True, primary_key=True)
    password = db.Column(db.String(254))
    enabled = db.Column(db.String(1))
    kelas = db.Column(db.String(64))
    individualname = db.Column(db.String(128))

    def hash_password(self, password):
        # self.password_hash = pwd_context.encrypt(password)
        self.password = 'plain:' + password

    def verify_password(self, password):
        password_hash = pwd_context.encrypt(self.password.split(':')[1])
        return pwd_context.verify(password, password_hash)

    # perhatikan token duration
    def generate_auth_token(self, expiration=60):
        # s = Serializer(app.config['SECRET_KEY'], expires_in=expiration)
        s = jwt.encode({'username': self.name, 'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}, app.config['SECRET_KEY'], algorithm='HS256')
        return s

    @staticmethod
    def verify_auth_token(token):
        print "token: ", token
        # s = Serializer(app.config['SECRET_KEY'])
        # s = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        s = jwt.encode({'username': token, 'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30)}, app.config['SECRET_KEY'], algorithm='HS256')
        try:
            data = jwt.decode(s,app.config['SECRET_KEY'], algorithms=['HS256'])
            print data
            # data = s.loads(token)
        except SignatureExpired:
            return None    # valid token, but expired
        except BadSignature:
            return None    # invalid token
        user = User.query.get(data['username'])
        return user

class UserSchema(ma.ModelSchema):
    class Meta:
        model = User

# class MetaList(db.Model):
#     __tablename__ = 't_metadata'

class Userwgroup(db.Model):
    __tablename__ = 'v_users'
    name = db.Column(db.String(128), index=True, primary_key=True)
    groupname = db.Column(db.String(128))
    rolename = db.Column(db.String(64))
    enabled = db.Column(db.String(1))
    individualname = db.Column(db.String(128))

class UserwgroupSchema(ma.ModelSchema):
    class Meta:
        model = Userwgroup 

class Group(db.Model):
    __tablename__ = 'groups'
    name = db.Column(db.String(128), index=True, primary_key=True)
    enabled = db.Column(db.String(1))
    organization = db.Column(db.String(128))
    url = db.Column(db.String(256))
    phone = db.Column(db.String(32))
    fax = db.Column(db.String(32))
    address = db.Column(db.Text)
    city = db.Column(db.String(64))
    administrativearea = db.Column(db.String(64))
    postalcode = db.Column(db.String(8))
    email = db.Column(db.String(128))
    country = db.Column(db.String(128))
    kodesimpul = db.Column(db.Text)

class GroupSchema(ma.ModelSchema):
    class Meta:
        model = Group

class Group_Members(db.Model):
    __tablename__ = 'group_members'
    groupname = db.Column(db.String(128), primary_key=True)
    username = db.Column(db.String(128), primary_key=True)

class Group_MembersSchema(ma.ModelSchema):
    class Meta:
        model = Group_Members    

class Roles(db.Model):
    __tablename__ = 'roles'
    name = db.Column(db.String(64), primary_key=True)
    parent = db.Column(db.String(64))

class RolesSchema(ma.ModelSchema):
    class Meta:
        model = Roles

class Group_Roles(db.Model):
    __tablename__ = 'group_roles'
    groupname = db.Column(db.String(128), primary_key=True)
    rolename = db.Column(db.String(64), primary_key=True)

class Group_RolesSchema(ma.ModelSchema):
    class Meta:
        model = Group_Roles

class User_Roles(db.Model):
    __tablename__ = 'user_roles'
    username = db.Column(db.String(128), primary_key=True)
    rolename = db.Column(db.String(64), primary_key=True)

class User_RolesSchema(ma.ModelSchema):
    class Meta:
        model = User_Roles        

class User_Props(db.Model):
    __tablename__ = 'user_props'
    username = db.Column(db.String(128), primary_key=True)
    propname = db.Column(db.String(64), primary_key=True)
    provalue = db.Column(db.String(2048))

class UserAuth(object):
    def __init__(self, username, password, kelas):
        self.username = username
        self.password = password
        self.kelas = kelas
    def __str__(self):
        return self.username
        # return "User(user='%s')" % self.username

class Metalinks(db.Model):
    __tablename__ = 'metalinks'
    identifier = db.Column(db.String(128), primary_key=True)
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.Text)
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)

class MetalinksSchema(ma.ModelSchema):
    class Meta:
        model = Metalinks        

class Metakugi(db.Model):
    __tablename__ = 'metakugi'
    identifier = db.Column(db.String(128), primary_key=True)
    skema = db.Column(db.String(128))
    fitur = db.Column(db.String(128))
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.Text)
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)
    tipe = db.Column(db.String(16))

class MetakugiSchema(ma.ModelSchema):
    class Meta:
        model = Metakugi            

class Metakugi_dev(db.Model):
    __tablename__ = 'metakugi_dev'
    identifier = db.Column(db.String(128), primary_key=True)
    skema = db.Column(db.String(128))
    fitur = db.Column(db.String(128))
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.Text)
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)
    tipe = db.Column(db.String(16))

class Metakugi_devSchema(ma.ModelSchema):
    class Meta:
        model = Metakugi_dev     

class Metakugi_prod(db.Model):
    __tablename__ = 'metakugi_prod'
    identifier = db.Column(db.String(128), primary_key=True)
    skema = db.Column(db.String(128))
    fitur = db.Column(db.String(128))
    workspace = db.Column(db.String(128))
    metatick =  db.Column(db.String(1))
    akses = db.Column(db.Text)
    published = db.Column(db.String(1))
    xml = db.Column(db.Text)
    tipe = db.Column(db.String(16))

class Metakugi_prodSchema(ma.ModelSchema):
    class Meta:
        model = Metakugi_prod             

class Sistem(db.Model):
    __tablename__ = 'sistem'
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text)

class SistemSchema(ma.ModelSchema):
    class Meta:
        model = Sistem        

class KodeEPSG(db.Model):
    __tablename__ = 'kode_epsg'
    kode = db.Column(db.Text, primary_key=True)
    keterangan = db.Column(db.Text)

class KodeEPSG_RolesSchema(ma.ModelSchema):
    class Meta:
        model = KodeEPSG          

class Front_layers(db.Model):
    __tablename__ = 'front_layers'
    id = db.Column(db.BigInteger, primary_key=True)
    layer_nativename = db.Column(db.String(256))
    layer_title =  db.Column(db.String(256))
    aktif = db.Column(db.Boolean)

class Front_layersSchema(ma.ModelSchema):
    class Meta:
        model = Front_layers   

class Grup_fitur(db.Model):
    __tablename__ = 'group_features'
    groupname = db.Column(db.String(128), primary_key=True)
    fitur = db.Column(db.String(256), primary_key=True)
    skema = db.Column(db.String(128))
    skala = db.Column(db.String(16))

class Grup_fiturSchema(ma.ModelSchema):
    class Meta:
        model = Grup_fitur

class FrontendTheme(db.Model):
    __tablename__ = 'front_end'
    key = db.Column(db.String(128), primary_key=True)
    value = db.Column(db.Text)

class FrontendThemeSchema(ma.ModelSchema):
    class Meta:
        model = FrontendTheme        


# FUNCTIONS

def identity(payload):
    print 'Identity:', user
    return user

@auth.verify_password
def verify_password(username_or_token, password):
    # first try to authenticate by token
    user = User.verify_auth_token(username_or_token)
    print "User: ", user
    if not user:
        # try to authenticate with username/password
        user = User.query.filter_by(name=username_or_token).first()
        if not user or not user.verify_password(password):
            return False
    user_auth = UserAuth(username_or_token, password, user.kelas)        
    g.user = user
    print 'User auth:', user_auth
    return user_auth

pjwt = JWT(app, verify_password, identity)    

# @auth.verify_password
# def verify_password(username_or_token, password):
#     # first try to authenticate by token
#     user = User.verify_auth_token(username_or_token)
#     if not user:
#         # try to authenticate with username/password
#         user = User.query.filter_by(name=username_or_token).first()
#         if not user or not user.verify_password(password):
#             return False
#     g.user = user
#     return True    

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    if request.method == 'OPTIONS':
        response.headers['Access-Control-Allow-Methods'] = 'DELETE, GET, POST, PUT'
        headers = request.headers.get('Access-Control-Request-Headers')
        if headers:
            response.headers['Access-Control-Allow-Headers'] = headers
    return response

# ROUTES ....

@app.route('/api/sisteminfo')
def sisteminfo():
    info = {}
    sisinfo = db.session.query(Sistem).all()
    for row in sisinfo:
        print row.key, row.value
        info[row.key] = row.value
    resp = json.dumps(info)
    print info
    return Response(resp, mimetype='application/json')    

@app.route('/api/sisteminfo/edit', methods=['POST'])
def sisteminfoedit():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        organization = urllib2.unquote(header['pubdata']['organization'])
        url = urllib2.unquote(header['pubdata']['url'])
        individualname = urllib2.unquote(header['pubdata']['individualname'])
        positionname = urllib2.unquote(header['pubdata']['positionname'])
        phone = urllib2.unquote(header['pubdata']['phone'])
        fax = urllib2.unquote(header['pubdata']['fax'])
        address = urllib2.unquote(header['pubdata']['address'])
        city = urllib2.unquote(header['pubdata']['city'])
        administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
        postalcode = urllib2.unquote(header['pubdata']['postalcode'])
        country = urllib2.unquote(header['pubdata']['country'])
        email = urllib2.unquote(header['pubdata']['email'])
        hoursofservice = urllib2.unquote(header['pubdata']['hoursofservice'])
        contactinstruction = urllib2.unquote(header['pubdata']['contactinstruction'])
        kodesimpul = urllib2.unquote(header['pubdata']['kodesimpul'])
        print header
        r_address = Sistem.query.filter_by(key='address').first()
        r_administrativearea = Sistem.query.filter_by(key='administrativearea').first()
        r_city = Sistem.query.filter_by(key='city').first()
        r_contactinstruction = Sistem.query.filter_by(key='contactinstruction').first()
        r_country = Sistem.query.filter_by(key='country').first()
        r_email = Sistem.query.filter_by(key='email').first()
        r_fax = Sistem.query.filter_by(key='fax').first()
        r_hoursofservice = Sistem.query.filter_by(key='hoursofservice').first()
        r_individualname = Sistem.query.filter_by(key='individualname').first()
        r_organization = Sistem.query.filter_by(key='organization').first()
        r_phone = Sistem.query.filter_by(key='phone').first()
        r_positionname = Sistem.query.filter_by(key='positionname').first()
        r_postalcode= Sistem.query.filter_by(key='postalcode').first()
        r_url = Sistem.query.filter_by(key='url').first()
        r_kodesimpul = Sistem.query.filter_by(key='kodesimpul').first()
        r_address.value = address
        r_administrativearea.value = administrativearea
        r_city.value = city
        r_contactinstruction.value = contactinstruction
        r_country.value = country
        r_email.value = email
        r_fax.value = fax
        r_hoursofservice.value = hoursofservice
        r_individualname.value = individualname
        r_organization.value = organization
        r_phone.value = phone
        r_positionname.value = positionname
        r_postalcode.value = postalcode
        r_url.value = url
        r_kodesimpul.value = kodesimpul
        db.session.commit()
        return jsonify({'Result': True, 'MSG':'Data sukses disimpan!'})

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return jsonify({'Result': False, 'MSG':'POST Only!'})
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data))
        # print 'User:', header['username'], 'Password:', header['password']
        try:
            if User.query.filter_by(name=header['username']).first() is not None:
                user = User.query.filter_by(name=header['username']).first() 
                print user
                # print 'User', user.name, 'Password', user.password
                if user.name == header['username']:   
                    if user.password.split(':')[1] == header['password']:
                        passw = base64.b64encode(header['password'])
                        group = Group_Members.query.filter_by(username=header['username']).first()
                        print 'Grup:',group
                        if group is not None:
                            return jsonify({'Result': True, 'MSG':'Valid Info', 'user':user.name, 'username':user.name, 'password':passw, 'kelas':user.kelas, 'grup':group.groupname, 'indiviualname':user.individualname})
                        else:
                            return jsonify({'Result': True, 'MSG':'Valid Info', 'user':user.name, 'username':user.name, 'password':passw, 'kelas':user.kelas, 'grup':'', 'indiviualname':user.individualname})
                    else:
                        return jsonify({'Result': False, 'MSG':'Password salah!'})
            else:
                return jsonify({'Result': False, 'MSG':'User tidak terdaftar!'})
        except:
            return jsonify({'Result': False, 'MSG':'Peace!'})

@app.route('/api/users', methods=['POST'])
# @auth.login_required
def new_user():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata'] ['name']
    name = re.sub('[\s+]', '', name)
    password = header['pubdata'] ['password']
    grup = header['pubdata'] ['grup']
    #role = header['pubdata'] ['role']
    role = grup
    kelas = header['pubdata'] ['kelas']
    enabled = header['pubdata'] ['enabled']
    individualname = urllib2.unquote(header['pubdata'] ['individualname'])
    if name is None or password is None:
        abort(400)    # missing arguments
    if User.query.filter_by(name=name).first() is not None:
        abort(400)    # existing user
    user = User(name=name)
    user.hash_password(password)
    user.enabled = 'Y'
    user.kelas = kelas
    user.individualname = individualname
    user_grup = Group_Members(groupname=grup)
    user_grup.groupname = grup
    user_grup.username = name
    user_role = User_Roles(rolename=role)
    user_role.rolename = role
    user_role.username = name
    db.session.add(user_role)
    db.session.add(user_grup)
    db.session.add(user)
    db.session.commit()
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()  
    sql_user = "CREATE USER \"%s\" WITH PASSWORD '%s';" % (str(name), str(password))
    cur.execute(sql_user)
    sql_grant = "GRANT \"%s\" to \"%s\";" % ('ROLE_'+str(grup), str(name))
    cur.execute(sql_grant)
    con.close()    
    resp = json.dumps({'RTN': True, 'MSG': 'Tambah pengguna berhasil!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/users/<string:name>')
def get_user(name):
    user = User.query.get(name)
    if not user:
        abort(400)
    return jsonify({'name': user.name})

@app.route('/api/users/list')
# @auth.login_required
def list_user():
    list_user = User.query.filter(User.name != 'admin').with_entities(User.name, User.enabled, User.individualname)
    users = UserSchema(many=True)
    output = users.dump(list_user)
    return json.dumps(output.data)

@app.route('/api/user/delete', methods=['POST'])
# @auth.login_required
def delete_user():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    if name is None:
        abort(400)
    if User.query.filter_by(name=name).first() is None:
        abort(400)
    if Group_Members.query.filter_by(username=name):
        Group_Members.query.filter_by(username=name).delete()
    if User_Roles.query.filter_by(username=name):
        User_Roles.query.filter_by(username=name).delete()
    user = User(name=name)
    User.query.filter_by(name=name).delete()
    db.session.commit()
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()  
    sql_user = "DROP USER \"%s\";" % str(name)
    cur.execute(sql_user)    
    con.close()    
    resp = json.dumps({'RTN': True, 'MSG': 'User dihapus!'})
    return Response(resp, mimetype='application/json')            

@app.route('/api/user/edit', methods=['POST'])
# @auth.login_required
def edit_user():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata'] ['name']
    try:
        password = header['pubdata']['password']
    except:
        password = ''
    try:
        grup = header['pubdata'] ['groupname']['value']
    except:
        grup = header['pubdata'] ['groupname']
    #role = header['pubdata'] ['role']
    role = grup
    # kelas = header['pubdata'] ['kelas']
    # enabled = header['pubdata'] ['enabled']
    individualname = urllib2.unquote(header['pubdata']['individualname'])
    try:
        print "HEAD"
        try:
            con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
            con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = con.cursor()  
            sqlm = "UPDATE group_members SET groupname='%s' WHERE username='%s';" % (str(grup), str(name))
            print "UPDATE Group_Members", sqlm
            cur.execute(sqlm)
            # selected_grup = Group_Members.query.filter_by(username=name).first
            # selected_grup.groupname = grup
            sqln = "UPDATE user_roles SET rolename='%s' WHERE username='%s';" % (str(grup), str(name))
            print "UPDATE User_Roles", sqln
            cur.execute(sqln)            
            # selected_role = User_Roles.query.filter_by(username=name).first
            # selected_role = grup
            print "A"
            con.close()
        except:
            con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
            con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = con.cursor()  
            sqlm = "INSERT INTO group_members (groupname, username) VALUES ('%s', '%s');" % (str(grup), str(name))
            print "INSERT Group_Members", sqlm
            cur.execute(sqlm)
            # selected_grup = Group_Members.query.filter_by(username=name).first
            # selected_grup.groupname = grup
            sqln = "INSERT INTO user_roles (rolename, username) VALUES ('%s', '%s');" % (str(grup), str(name))
            print "INSERT User_Roles", sqln
            cur.execute(sqln)            
            # selected_role = User_Roles.query.filter_by(username=name).first
            # selected_role = grup
            print "B"
            con.close()
            # selected_grup = Group_Members(groupname=grup)
            # selected_grup.groupname = grup
            # selected_grup.username = name
            # db.session.add(selected_grup)
            # selected_role = User_Roles(rolename=grup)
            # selected_role.rolename = grup
            # selected_role.username = name  
            # db.session.add(selected_role)          
            # print "B"
            # db.session.commit()  
        try:
            if password != '':
                p_password = 'plain:' + password 
            con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
            con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = con.cursor()  
            sqlm = "UPDATE users SET password='%s' WHERE name='%s';" % (str(p_password), str(name))
            print "UPDATE password", sqlm
            cur.execute(sqlm)  
            sqln = "ALTER USER \"%s\" WITH PASSWORD '%s';" % (str(name), str(p_password))
            cur.execute(sqln)                           
            con.close()
            print "C"
            resp = json.dumps({'RTN': True, 'MSG': 'Sukses!'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Error!'})
        # selected_user = User.query.filter_by(name=name).first()
        # if password != '':
        #     selected_user.password = 'plain:' + password
        # selected_user.individualname = individualname
        # db.session.commit()              
        # resp = json.dumps({'RTN': True, 'MSG': 'Sukses!'})
    except:
        resp = json.dumps({'RTN': False, 'MSG': 'Error!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/userswgroup/list')
# @auth.login_required
def list_userswgroup():
    list_userswgroup = Userwgroup.query.filter(Userwgroup.name != 'admin').with_entities(Userwgroup.name, Userwgroup.groupname, Userwgroup.rolename, Userwgroup.enabled, Userwgroup.individualname)
    users = UserwgroupSchema(many=True)
    output = users.dump(list_userswgroup)
    return json.dumps(output.data)    

@app.route('/api/groups', methods=['POST'])
# @auth.login_required
def new_groups():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = urllib2.unquote(header['pubdata']['name'])
    name = re.sub('[\s+]', '', name)
    print "NAME:", name
    organization = urllib2.unquote(header['pubdata']['organization'])
    url = header['pubdata']['url'] 
    phone = header['pubdata']['phone'] 
    fax = header['pubdata']['fax'] 
    address = urllib2.unquote(header['pubdata']['address'])
    city = urllib2.unquote(header['pubdata']['city'])
    administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
    postalcode = header['pubdata']['postalcode'] 
    email = header['pubdata']['email'] 
    country = "Indonesia"
    kodesimpul = urllib2.unquote(header['pubdata']['kodesimpul'])
    print 'Grup Baru:', name
    if name is None:
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
        return Response(resp, mimetype='application/json')
        abort(400)
    if Group.query.filter_by(name=name).first() is not None:
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'Error, Grup sudah ada!'})
        return Response(resp, mimetype='application/json')
        abort(400)
    if Roles.query.filter_by(name=name).first() is not None:
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'Error, Role sudah ada!'})
        return Response(resp, mimetype='application/json')
        abort(400)   
    con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()
    sql_role = "CREATE ROLE \"%s\";" % ('ROLE_'+str(name))
    cur.execute(sql_role)
    sql ="CREATE DATABASE \"%s\" ENCODING 'UTF-8' TEMPLATE template_postgis_wraster OWNER \"%s\";" % (str(name), str(app.config['DATASTORE_USER']))
    cur.execute(sql)
    sql_grant = "GRANT ALL PRIVILEGES ON DATABASE \"%s\" TO \"%s\";"  % (str(name),'ROLE_'+str(name))
    cur.execute(sql_grant)
    # KUGI TEMPLATES
    sql_kugi ="CREATE DATABASE \"%s\" ENCODING 'UTF-8' TEMPLATE template_palapa OWNER \"%s\";" % (str(name) + '_DEV', str(app.config['DATASTORE_USER']))
    cur.execute(sql_kugi)
    sql_grant_kugi = "GRANT ALL PRIVILEGES ON DATABASE \"%s\" TO \"%s\";"  % (str(name) + '_DEV','ROLE_'+str(name))
    cur.execute(sql_grant_kugi)    
    # sql_grant_kugiprod = "GRANT SELECT ON ALL TABLES IN SCHEMA public TO xxx; \"%s\" TO \"%s\";"  % ('palapa_prod'','ROLE_'+str(name))
    # cur.execute(sql_grant_kugiprod)       
    con.close()
    group = Group(name=name,organization=organization,url=url,phone=phone,fax=fax,address=address,city=city,administrativearea=administrativearea,postalcode=postalcode,email=email,country=country,kodesimpul=kodesimpul)
    role = Roles(name=name)
    group.enabled =  header['pubdata']['enabled'] 
    db.session.add(group)
    db.session.add(role)
    db.session.commit()
    # Create Store
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    new_workspace = catalog.create_workspace(name,name)
    new_store = catalog.create_datastore(name,name)
    new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database=name,user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
    # layers security
    with open(app.config['GEOSERVER_LAYERS_PROP'], 'a') as file:
        file.write(name + '.*.a=' + name + '\n')
    catalog.save(new_store)
    catalog.reload()
        # return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    resp = json.dumps({'RTN': 'OK', 'MSG': 'Grup ' + name + ' selesai dibuat!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/group/edit', methods=['POST'])
def groupedit():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata']     
    name = header['pubdata']['name'] 
    organization = urllib2.unquote(header['pubdata']['organization'])
    url = header['pubdata']['url'] 
    phone = header['pubdata']['phone'] 
    fax = header['pubdata']['fax'] 
    address = urllib2.unquote(header['pubdata']['address'])
    city = urllib2.unquote(header['pubdata']['city'])
    administrativearea = urllib2.unquote(header['pubdata']['administrativearea'])
    postalcode = header['pubdata']['postalcode'] 
    email = header['pubdata']['email'] 
    country = "Indonesia"
    kodesimpul = header['pubdata']['kodesimpul'] 
    selected_group = Group.query.filter_by(name=name).first()
    selected_group.organization = organization
    selected_group.url = url
    selected_group.phone = phone
    selected_group.fax = fax
    selected_group.address = address
    selected_group.city = city
    selected_group.administrativearea = administrativearea
    selected_group.postalcode = postalcode
    selected_group.email = email
    selected_group.country = country
    selected_group.kodesimpul = kodesimpul
    db.session.commit()
    return jsonify({'MSG': 'Grup %s diperbaharui.' % name})   

@app.route('/api/preparekugi', methods=['POST'])
# @auth.login_required
def kugiprepare():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    print 'Grup Baru:', name
    if name is None:
        print 'No Group name'
        abort(400)
    if Group.query.filter_by(name=name).first() is not None:
        print 'Grup sudah ada'
        abort(400)
    if Roles.query.filter_by(name=name).first() is not None:
        print 'Role sudah ada'
        abort(400)    
    group = Group(name=name)
    role = Roles(name=name)
    group.enabled = 'Y'
    db.session.add(group)
    db.session.add(role)
    db.session.commit()
    print 'Commited'
    catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    new_workspace = catalog.create_workspace(name,name)
    # con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
    # con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    # cur = con.cursor()
    # sql ="CREATE DATABASE \"%s\" ENCODING 'UTF-8' TEMPLATE template_postgis_wraster owner \"%s\";" % (str(name), str(app.config['DATASTORE_USER']))
    # cur.execute(sql)
    # print sql
    # Create Store
    new_store = catalog.create_datastore(name,name)
    new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database='palapa_pub',user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
    # layers security
    with open(app.config['GEOSERVER_LAYERS_PROP'], 'a') as file:
        file.write(name + '.*.a=' + name + '\n')
    catalog.save(new_store)
    catalog.reload()
        # return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    return (jsonify({'group': group.name}), 201,
            {'Location': url_for('get_group', name=group.name, _external=True)})

@app.route('/api/group/list')
# @auth.login_required
def list_group():
    list_group = User.query.with_entities(Group.name, Group.enabled, Group.organization, Group.url, Group.phone, Group.fax, Group.address, Group.city, Group.administrativearea, Group.postalcode, Group.email, Group.country, Group.kodesimpul)
    groups = GroupSchema(many=True)
    output = groups.dump(list_group)
    return json.dumps(output.data)        

@app.route('/api/role/list')
# @auth.login_required
def list_role():
    list_role = User.query.with_entities(Roles.name, Roles.parent)
    roles = RolesSchema(many=True)
    output = roles.dump(list_role)
    return json.dumps(output.data)        

@app.route('/api/group/delete', methods=['POST'])
# @auth.login_required
def delete_groups():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header['pubdata'] 
    name = header['pubdata']['name'] 
    if name is None:
        abort(400)
    if Group.query.filter_by(name=name).first() is None:
        abort(400)
    group = Group(name=name)
    copyfile(app.config['GEOSERVER_LAYERS_PROP'], app.config['GEOSERVER_LAYERS_PROP'] + '.bak')
    with open(app.config['GEOSERVER_LAYERS_PROP'] + '.bak') as oldfile, open(app.config['GEOSERVER_LAYERS_PROP'], 'w') as newfile:
        for line in oldfile:
            if not name in line:
                newfile.write(line)
    Group.query.filter_by(name=name).delete()
    if Group_Members.query.filter_by(groupname=name):
        Group_Members.query.filter_by(groupname=name).delete()    
    if Roles.query.filter_by(name=name):
        Roles.query.filter_by(name=name).delete()    
    if User_Roles.query.filter_by(rolename=name):
        User_Roles.query.filter_by(rolename=name).delete()
    db.session.commit()    
    con = psycopg2.connect(dbname=cfg.DATASTORE_DB, user=cfg.DATASTORE_USER, host=cfg.DATASTORE_HOST, password=cfg.DATASTORE_PASS)
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = con.cursor()  
    sql_deldb1 = "ALTER DATABASE \"%s\" CONNECTION LIMIT 1;" % str(name)
    cur.execute(sql_deldb1)    
    sql_deldb2 = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s';" % str(name)
    cur.execute(sql_deldb2)    
    sql_deldb3 = "DROP DATABASE \"%s\";" % str(name)
    cur.execute(sql_deldb3)    
    sql_deldb5 = "DROP DATABASE \"%s\";" % str(name + '_DEV')
    cur.execute(sql_deldb5)     
    sql_deldb4 = "DROP ROLE IF EXISTS \"%s\";" % str("ROLE_" + name)
    cur.execute(sql_deldb4)        
    con.close()
    catalog = Catalog(cfg.GEOSERVER_REST_URL, cfg.GEOSERVER_USER, cfg.GEOSERVER_PASS)
    shutil.rmtree(cfg.GEOSERVER_DATA_DIR + 'workspaces/' + name)
    try:
        store = catalog.get_store(name)
        catalog.delete(store)
        catalog.reload()
    except:
        pass
    try:
        ns = catalog.get_workspace(name)
        catalog.delete(ns)
        catalog.reload()    
    except:
        pass
    return jsonify({'MSG': 'Grup %s dihapus.' % group.name})            

@app.route('/api/group/<string:name>')
def get_group(name):
    group = Group.query.filter_by(name=name)
    group_info = GroupSchema(many=True)
    output = group_info.dump(group)
    if not group:
        abort(400)
    return json.dumps(output.data)            

@app.route('/api/token')
@auth.login_required
def get_auth_token():
    token = g.user.generate_auth_token(60)
    return jsonify({'token': token.decode('ascii'), 'duration': 60})

@app.route('/api/resource')
@jwt_required()
def get_resource():
    return jsonify({'data': 'Hello, %s!' % g.user.name})

# GeoServer REST fetch

@app.route('/api/getWMSlayers')
def get_wmslayers():
  workspaces = get_gs_namespaces()
  styles = get_gs_styles()
  layers = get_gs_layers()
  matches = []
  gslayers = []
  for root, dirnames, filenames in os.walk(cfg.GEOSERVER_DATA_DIR + 'workspaces'):
    gslayer = {}
    for filename in fnmatch.filter(filenames, 'featuretype.xml'):
      thefile = os.path.join(root, filename)
      matches.append(thefile)
      try:
        mtime = os.path.getmtime(thefile)
      except OSError:
        mtime = 0
      moddate = dt.fromtimestamp(mtime)
      with open(thefile) as curfile:
        xml = curfile.read()
      content = xmltodict.parse(xml)
      gslayer['layer_name'] = content['featureType']['title']
      gslayer['layer_id'] = content['featureType']['nativeName']
      namespace_id = content['featureType']['namespace']['id']
      layer_id = content['featureType']['id']
      try:
        gslayer['layer_abstract'] = content['featureType']['abstract']
      except:
        gslayer['layer_abstract'] = ''
      gslayer['layer_srs'] = content['featureType']['srs']
      gslayer['layer_minx'] = float(content['featureType']['latLonBoundingBox']['minx'])
      gslayer['layer_maxx'] = float(content['featureType']['latLonBoundingBox']['maxx'])
      gslayer['layer_miny'] = float(content['featureType']['latLonBoundingBox']['miny'])
      gslayer['layer_maxy'] = float(content['featureType']['latLonBoundingBox']['maxy'])
      gslayer['layer_aktif'] = str_to_bool(content['featureType']['enabled'].capitalize())
      gslayer['last_modified'] = moddate.strftime('%Y-%m-%d %H:%M:%S')
      for namespace in workspaces:
        if namespace['id'] == namespace_id:
          gslayer['workspace'] = namespace['name']
          gslayer['layer_nativename'] = namespace['name'] + ':' + content['featureType']['nativeName']
      for layer in layers:
        if layer['id'] == layer_id:
          defaultStyle_id = layer['defaultStyle_id']
          gslayer['layer_type'] = layer['type']
          for style in styles:
            if style['id'] == defaultStyle_id:
              gslayer['layer_style'] = style['name']
      gslayers.append(gslayer)   
      gslayer = {}       
    for filename in fnmatch.filter(filenames, 'coverage.xml'):
      thefile = os.path.join(root, filename)
      matches.append(thefile)
      try:
        mtime = os.path.getmtime(thefile)
      except OSError:
        mtime = 0
      moddate = dt.fromtimestamp(mtime)
      with open(thefile) as curfile:
        xml = curfile.read()
      content = xmltodict.parse(xml)
      gslayer['layer_name'] = content['coverage']['title']        
      gslayer['layer_id'] = content['coverage']['nativeName']
      namespace_id = content['coverage']['namespace']['id']
      layer_id = content['coverage']['id']
      try:
        gslayer['layer_abstract'] = content['coverage']['abstract']
      except:
        gslayer['layer_abstract'] = ''
      gslayer['layer_srs'] = content['coverage']['srs']
      gslayer['layer_minx'] = float(content['coverage']['latLonBoundingBox']['minx'])
      gslayer['layer_maxx'] = float(content['coverage']['latLonBoundingBox']['maxx'])
      gslayer['layer_miny'] = float(content['coverage']['latLonBoundingBox']['miny'])
      gslayer['layer_maxy'] = float(content['coverage']['latLonBoundingBox']['maxy'])
      gslayer['layer_aktif'] = str_to_bool(content['coverage']['enabled'].capitalize())
      gslayer['last_modified'] = moddate.strftime('%Y-%m-%d %H:%M:%S')
      for namespace in workspaces:
        if namespace['id'] == namespace_id:
          gslayer['workspace'] = namespace['name']
          gslayer['layer_nativename'] = namespace['name'] + ':' + content['coverage']['nativeName']
      for layer in layers:
        if layer['id'] == layer_id:
          defaultStyle_id = layer['defaultStyle_id']
          gslayer['layer_type'] = layer['type']   
          for style in styles:
            if style['id'] == defaultStyle_id:
              gslayer['layer_style'] = style['name']         
      gslayers.append(gslayer) 
      gslayer = {}  
  resp = json.dumps(gslayers) 
  return Response(resp, mimetype='application/json')

@app.route('/api/getstyles')
# @auth.login_required
def get_styles():
    styles = georest_get(app.config['GEOSERVER_REST_URL'] + 'styles.json', app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    return json.dumps(styles['styles']['style'])   

# GeoServer REST POST

@app.route('/api/styles/add', methods=['POST'])
# @auth.login_required
def add_style():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_sld(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_sld(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            print "Filename: " + filename.split('.')[0]
            sldfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.sld'
            print "Shapefile: " + sldfile
            if os.path.exists(sldfile):
                print "File SLD OK"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                sld = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                try:
                    catalog.create_style(filename.split('.')[0], sld.read()) 
                    resp = json.dumps({'RTN': filename, 'MSG': 'Upload Success!'})
                except:
                    resp = json.dumps({'RTN': filename, 'MSG': 'Error, Style dengan nama yang sama sudah ada!'})
                return Response(resp, mimetype='application/json')
            else:
                resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'ERROR'})
        return Response(resp, mimetype='application/json')    
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/styles/modify')
# @auth.login_required
def modify_style():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/styles/delete', methods=['POST'])
# @auth.login_required
def delete_style():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print header['pubdata'] 
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        style = catalog.get_style(header['pubdata'])
        catalog.delete(style)
        catalog.reload()
        return jsonify({'RTN': 'Deleted!'})

@app.route('/api/layers/info/<string:layers>')
# @auth.login_required
def layer_info(layers):
    decoded_url = app.config['GEOSERVER_REST_URL'] + 'layers/' + layers + '.json'
    print decoded_url
    resource_info = {}
    resource = georest_get(decoded_url, app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
    resource_info['name']=resource['layer']['name']
    resource_info['defaultstyle']=resource['layer']['defaultStyle']['name']
    resource_info['type']=resource['layer']['type']
    return jsonify(resource_info)

@app.route('/api/layers/add')
# @auth.login_required
def add_layer():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layers/modify', methods=['POST'])
# @auth.login_required
def modify_layer():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print header['pubdata']
        try:
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            resource = catalog.get_resource(header['pubdata']['id'])
            resource.title = urllib2.unquote(header['pubdata']['title'])
            resource.abstract = urllib2.unquote(header['pubdata']['abstract'])
            resource.enabled = header['pubdata']['aktif']
            try:
                if header['pubdata']['style']['value']:
                    set_style = header['pubdata']['style']['value']
            except:
                set_style = header['pubdata']['style']
            catalog.save(resource)
            catalog.reload()
            if header['pubdata']['tipe'] == 'VECTOR':
                layer = catalog.get_layer(header['pubdata']['nativename'])
                layer._set_default_style(set_style)
                msg = 'Set vector style'
            if header['pubdata']['tipe'] == 'RASTER':
                layer = catalog.get_layer(header['pubdata']['id'])
                layer._set_default_style(set_style)
                msg ='Set raster style'
            catalog.save(layer)
            catalog.reload()
            resp = json.dumps({'RTN': True, 'MSG': 'Informasi layer berhasil diedit'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Informasi layer gagal diedit'})    
        return Response(resp, mimetype='application/json')        

@app.route('/api/layers/delete', methods=['POST'])
# @auth.login_required
def delete_layer():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print 'Pubdata:', header['pubdata'] 
        try:
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            layer = catalog.get_layer(header['pubdata']['layer'])
            workspace = header['pubdata']['workspace']
            del_layer = catalog.delete(layer)
            catalog.reload()
            print  workspace
            if workspace == 'KUGI':
                try:
                    delete_metakugi(header['pubdata']['layer'])
                    resp = json.dumps({'RTN': True, 'MSG': 'Layer berhasil dihapus'})
                except:
                    resp = json.dumps({'RTN': False, 'MSG': 'Layer gagal dihapus'})
            else:
                try:
                    delete_metadata(header['pubdata']['workspace']+":"+header['pubdata']['layer'])
                    delete_metalinks(header['pubdata']['layer'])
                    con = psycopg2.connect(dbname=workspace, user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
                    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                    cur = con.cursor()
                    sql ="DROP TABLE %s CASCADE;" % (str(header['pubdata']['layer']))
                    print(sql)
                    cur.execute(sql)                    
                    resp = json.dumps({'RTN': True, 'MSG': 'Layer berhasil dihapus'})
                except:
                    resp = json.dumps({'RTN': False, 'MSG': 'Layer gagal dihapus'})    
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Layer gagal dihapus'}) 
        return Response(resp, mimetype='application/json')   

@app.route('/api/layers/populate/<string:file>', methods=['POST'])
# @auth.login_required
def populate_layer(file):
    if request.method == 'POST':
        return jsonify({'RTN': 'File ' + file + ' dimuat ke database.'})
    return jsonify({'RTN': 'R.I.P'})

@app.route('/api/workspace/add/<string:workspace>', methods=['POST'])
# @auth.login_required
def add_workspace(workspace):
    if request.method == 'POST':
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        new_workspace = catalog.create_workspace(workspace,workspace)
        return jsonify({'RTN': 'Workspace ' + workspace + ' dibuat.'})
    return jsonify({'RTN': 'Permintaan salah!'})

@app.route('/api/workspace/modify')
# @auth.login_required
def modify_workspace():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/workspace/delete')
# @auth.login_required
def delete_workspace():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/store/add/<string:store>', methods=['POST'])
# @auth.login_required
def add_store(store):
    if request.method == 'POST':
        # Create database
        sqlalchemy_utils.create_database(app.config['SQLALCHEMY_DATASTORE'] + store, encoding='utf8', template='template_postgis')
        # Create Store
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        new_store = catalog.create_datastore(store,store)
        new_store.connection_parameters.update(host=app.config['DATASTORE_HOST'], port=app.config['DATASTORE_PORT'], database=store,user=app.config['DATASTORE_USER'], passwd=app.config['DATASTORE_PASS'], dbtype='postgis', schema='public')
        catalog.save(new_store)
        catalog.reload()
        return jsonify({'RTN': 'Store PostGIS ' + store + ' dibuat.'})
    return jsonify({'RTN': 'Permintaan salah!'})

@app.route('/api/store/modify')
# @auth.login_required
def modify_store():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/store/delete')
# @auth.login_required
def delete_store():
    return jsonify({'RTN': 'Hello!'})    

@app.route('/api/layergroup/add')
# @auth.login_required
def add_layergroup():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layergroup/modify')
# @auth.login_required
def modify_layergroup():
    return jsonify({'RTN': 'Hello!'})

@app.route('/api/layergroup/delete')
# @auth.login_required
def delete_layergroup():
    return jsonify({'RTN': 'Hello!'})      
    
@app.route('/api/upload', methods=['POST'])
# @auth.login_required
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        user = request.args.get('USER')
        grup = request.args.get('GRUP')
        kodesimpul = request.args.get('KODESIMPUL')
        print 'User:',user, 'Grup:', grup, 'Kode:', kodesimpul
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_file(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            unzip(filename,filename)
            for f in app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]:
                path, ext = os.path.splitext(f)
                if ext.isupper():
                    os.rename(f, path + ext.lower())
            for berkas in os.listdir(app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]):
                if berkas.endswith(".tif") or berkas.endswith(".TIF") or berkas.endswith(".tiff") or berkas.endswith(".TIFF"):
                    print "Filename: " + filename.split('.')[0]
                    populate = populateRS(filename.split('.')[0],kodesimpul)
                    lid = populate[2]
                    SEPSG = populate[1].split(':')[1]
                    resp = json.dumps({'RTN': filename, 'MSG': 'Unggah data sukses! Proyeksi terdeteksi sebagai: ' + populate[1], 'EPSG': populate[1], 'SEPSG': SEPSG, 'ID': populate[2], 'TID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                    return Response(resp, mimetype='application/json')                    
                if berkas.endswith(".shp") or berkas.endswith(".SHP"):
                    shapefile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '/' + filename.split('.')[0] + '.shp'
                    print "Shapefile: " + shapefile
                    if os.path.exists(shapefile):
                        print "File SHP OK"
                        populate = populateDB(filename,grup,kodesimpul)
                        lid = populate[2]+'-'+populate[3]
                        SEPSG = populate[1].split(':')[1]
                        resp = json.dumps({'RTN': filename, 'MSG': 'Unggah data sukses!' + populate[0], 'EPSG': populate[1], 'SEPSG': SEPSG, 'ID': populate[2], 'TID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                        return Response(resp, mimetype='application/json')
                    else:
                        resp = json.dumps({'RTN': 'ERR', 'MSG': 'No SHAPE file!'})
                        return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'ERROR'})
        return Response(resp, mimetype='application/json')
        
@app.route('/api/uploads/<string:filename>')
# @auth.login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'],filename)

@app.route('/api/proxy/<path:url>')
def home(url):
    req = request.args.get(url)
    return req

@app.route('/api/feature/<string:feature>/<string:identifier>')
def return_feature(feature, identifier):
    return jsonify({'RTN': feature + ' ' + identifier})

@app.route('/api/publish', methods=['POST'])
def return_publish():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print "GS Params:", header
        print header['pubdata']['LID']
        tipe = header['pubdata']['TIPE']
        layer_id = header['pubdata']['LID']
        user = header['pubdata']['USER']
        grup = header['pubdata']['GRUP']
        kode_epsg = 'EPSG:' + header['pubdata']['SEPSG'] 
        try:
            if tipe == 'RASTER':
                print "RASTER"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                workspace = catalog.get_workspace(grup)
                datastore = catalog.get_store(grup)
                # sf = catalog.get_workspace(workspace)
                ft_ext = catalog.create_coveragestore_external_geotiff(layer_id, 'file:'+app.config['RASTER_STORE']+layer_id+'.tif', workspace)
                resource = catalog.get_resources(layer_id)
                resource[0].title = urllib2.unquote(header['pubdata']['ID'])
                resource[0].abstract = urllib2.unquote(header['pubdata']['ABS'])
                resource[0].enabled = False
                resource[0].advertised = True
                resource[0].projection = kode_epsg
                catalog.save(resource[0])
                catalog.reload()
            if tipe == 'VECTOR':
                print "VECTOR"
                catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                workspace = catalog.get_workspace(grup)
                datastore = catalog.get_store(grup)
                publish = catalog.publish_featuretype(header['pubdata']['LID'], datastore, kode_epsg)
                publish.title = urllib2.unquote(header['pubdata']['ID'])
                publish.abstract = urllib2.unquote(header['pubdata']['ABS'])
                publish.enabled = False
                publish.advertised = True
                catalog.save(publish)
                catalog.reload()
            metalinks = Metalinks(identifier=layer_id)
            metalinks.workspace = grup
            db.session.add(metalinks)
            db.session.commit()
            # wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
            # bbox = wms[grup+':'+layer_id].boundingBoxWGS84       
            # print 'BBOX:', bbox
            # thumbnail = wms.getmap(layers=[header['pubdata']['LID']],srs=header['pubdata']['EPSG'],bbox=bbox,size=(300,300),format='image/png',transparent=True)
            # file = app.config['GEOSERVER_THUMBNAILS'] + layer_id+'.png'
            # print 'File:', file
            # outfile = open(file, 'wb')
            # outfile.write(thumbnail.read())
            # outfile.close()
            resp = json.dumps({'RTN': True, 'MSG': 'Sukses menyimpan layer'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Gagal menyimpan layer'})
    return Response(resp, mimetype='application/json')    

@app.route('/api/checkworkspace', methods=['POST'])
def checkworkspace():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])    
        wrk = header['pubdata']['workspace']
        print wrk
        catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
        workspace = catalog.get_workspace(wrk)
        if workspace is None:
            resp = json.dumps({'RTN': 'NA'})
        else:
            resp = json.dumps({'RTN': 'OK'})
        return Response(resp, mimetype='application/json')  

@app.route('/api/kugitogeo')
def kugitogeo():
    list_kugipub = User.query.with_entities(Group.name, Group.enabled)
    groups = GroupSchema(many=True)
    output = groups.dump(list_group)
    resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
    return Response(resp, mimetype='application/json')    

@app.route('/api/publishkugi', methods=['POST'])
def return_publishkugi():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print(header)
        skema = header['pubdata']['skema']
        fitur = header['pubdata']['fitur']
        dest_db = header['pubdata']['dest_db']
        try:
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            workspace = catalog.get_workspace('KUGI')
            datastore = catalog.get_store('KUGI')
            publish = catalog.publish_featuretype(fitur, datastore, 'EPSG:4326')
            publish.title = urllib2.unquote(fitur)
            publish.abstract = urllib2.unquote(fitur)
            publish.enabled = False
            publish.advertised = True
            catalog.save(publish)
            catalog.reload()
            # identifier = 'KUGI:' + fitur
            # metakugi = Metakugi(identifier=identifier)
            # metakugi.workspace = 'KUGI'
            # metakugi.skema = skema
            # metakugi.fitur = fitur
            # metakugi.tipe = 'induk'
            # engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
            # result = engine.execute("select feature, dataset, fileidentifier from a_view_fileidentifier where feature='" + fitur + "' group by feature, dataset, fileidentifier")
            # try:
            #     for row in result:
            #         anakidentifier = 'KUGI:' + fitur + '_' + row[2]
            #         print "Anak:", anakidentifier
            #         anakmetakugi = Metakugi(identifier=anakidentifier)
            #         anakmetakugi.workspace = 'KUGI'
            #         anakmetakugi.skema = skema
            #         anakmetakugi.fitur = fitur
            #         anakmetakugi.tipe = 'anak'
            #         db.session.add(anakmetakugi)
            #         db.session.commit()
            # except:
            #     resp = json.dumps({'MSG': 'ERROR'})            
            # db.session.add(metakugi)
            # db.session.commit()            
            resp = json.dumps({'RTN': 'OK', 'MSG': 'Publikasi layer ke GeoServer Sukses'})
        except:
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'POST ERROR'})
        return Response(resp, mimetype='application/json')

@app.route('/api/layer/adv', methods=['POST'])
def layer_adv():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print(header)
        toggle = header['pubdata']['aktif']
        try:
            catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
            resource = catalog.get_resource(header['pubdata']['id'])
            resource.title = urllib2.unquote(header['pubdata']['title'])
            resource.abstract = urllib2.unquote(header['pubdata']['abstract'])
            resource.enabled = header['pubdata']['aktif']
            layer_id = header['pubdata']['id']
            layer_workspace = header['pubdata']['nativename'].split(':')[0]
            layer_tipe = header['pubdata']['tipe']
            catalog.save(resource)
            catalog.reload()
            if header['pubdata']['tipe'] == 'VECTOR':
                layer = catalog.get_layer(header['pubdata']['nativename'])
                res = layer.resource
                if toggle == False:
                    print "STAT1",res.enabled
                    res.enabled = 'true'
                else:
                    print "STAT2",res.enabled
                    res.enabled = 'false'
            if header['pubdata']['tipe'] == 'RASTER':
                layer = catalog.get_layer(header['pubdata']['id'])
                res = layer.resource
                if toggle == False:
                    print "STAT3",res.enabled
                    res.enabled = 'true'
                else:
                    print "STAT4",res.enabled
                    res.enabled = 'false'
            catalog.save(res)
            catalog.reload()
            # time.sleep(5)
            if toggle == False:
                # try:
                #     print("Tier1")
                #     pycswadv(layer_id,layer_workspace,layer_tipe)
                # except:
                #     print("ERR")
                print(layer_id,layer_workspace,layer_tipe) 
                pycsw_publish = pycswadv(layer_id,layer_workspace,layer_tipe)
                print(pycsw_publish)    
                resp = json.dumps({'RTN': True, 'MSG': 'Layer sukses diaktifkan'})
            else:
                # try: 
                #     print("Tier1")
                #     pycswdel(layer_id, layer_workspace)
                # except:
                #     print("ERR2")
                print(layer_id,layer_workspace,layer_tipe) 
                pycsw_delete = pycswdel(layer_id, layer_workspace)
                print(pycsw_delete)    
                resp = json.dumps({'RTN': True, 'MSG': 'Layer sukses di non-aktifkan'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Layer gagal diaktifkan-kan'})
        return Response(resp, mimetype='application/json')  

@app.route('/api/cswRecords')
def record_list():
    csw = CatalogueServiceWeb(app.config['CSW_URL'])
    record = {}
    records = []
    try:
        csw.getrecords2(maxrecords=9999999)
        for rec in csw.records:
            record['identifier'] = csw.records[rec].identifier
            record['title'] = csw.records[rec].title
            record['abstract'] = csw.records[rec].abstract
            record['bbox_wgs84'] = csw.records[rec].bbox_wgs84
            record['subjects'] = csw.records[rec].subjects
            record['maxx'] = csw.record[rec].bbox.maxx
            record['maxy'] = csw.record[rec].bbox.maxy
            record['minx'] = csw.record[rec].bbox.minx
            record['miny'] = csw.record[rec].bbox.miny
            records.append(record)
            record = {}
        getrecords = json.dumps(records)
    except:
        getrecords = json.dumps({'ERR':'No Record(s)!'})
    return Response(getrecords, mimetype='application/json')

@app.route('/api/pycswRecords')
def pycsw_records():
    request_param = '?service=CSW&version=2.0.2&request=GetRecords&ElementSetName=full&typenames=csw:Record&resultType=results&outputformat=application/json'
    csw = pycsw_get(app.config['CSW_URL'], request_param)
    # print csw
    record = {}
    records = []    
    try:
        for rec in csw['csw:GetRecordsResponse']['csw:SearchResults']['csw:Record']:
            # print rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[0]
            try:
                record['identifier'] = rec['dc:identifier']
            except:
                pass
            try:
                record['title'] = rec['dc:title']
            except:
                pass
            try:
                record['abstract'] = rec['dct:abstract']
            except:
                pass
            try:
                record['type'] = rec['dc:type']
            except:
                pass
            # record['subjects'] = csw.records[rec].subjects
            try:
                record['maxx'] = rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[0]
            except:
                pass
            try:
                record['maxy'] = rec['ows:BoundingBox']['ows:UpperCorner'].split(' ')[1]
            except:
                pass
            try:
                record['minx'] = rec['ows:BoundingBox']['ows:LowerCorner'].split(' ')[0]
            except:
                pass
            try:
                record['miny'] = rec['ows:BoundingBox']['ows:LowerCorner'].split(' ')[1]
            except:
                pass
            try:
                record['thumbnails'] = record['identifier'].split(':')[1]
            except:
                pass
            try:
                for ref in rec['dct:references']:
                    if ref['@scheme'] == 'OGC:WMS':
                        record['WMS'] = 'OGC:WMS'
                    if ref['@scheme'] == 'OGC:WFS':
                        record['WFS'] = 'OGC:WFS'
            except:
                pass        
            records.append(record)
            record = {}
        print records    
        getrecords = json.dumps(records)
        print getrecords
    except:
        getrecords = json.dumps({'ERR':'No Record(s)!'})
    return Response(getrecords, mimetype='application/json')   

@app.route('/api/pycswRecord/insert', methods=['POST'])
def pycsw_insert():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        #xml_payload = urllib2.unquote(header['pubdata']['xml'])
        identifier = header['pubdata']['identifier']
        workspace = header['pubdata']['workspace']
        akses = header['pubdata']['akses']
        if workspace == 'KUGI':
            fitur = header['pubdata']['fitur']
        if workspace == 'KUGI':
            try:
                tipe = header['pubdata']['tipe']
                fi = workspace + ':' + fitur
                xmlmeta = Metakugi.query.filter_by(identifier=identifier).first()
                xml_payload = xmlmeta.xml
            except:
                pass
        else:
            fi = workspace + ':' + identifier
            xmlmeta = Metalinks.query.filter_by(identifier=identifier).first()
            xml_payload = xmlmeta.xml
        mcf_template = parse_big_md(xml_payload)
        try:
            print "Identifier:", header['pubdata']['identifier']
            print "Workspace:", header['pubdata']['workspace']
            print "Akses:", header['pubdata']['akses']
            print fi
            if akses == 'PUBLIC':
                restriction = 'unclassified'
            if akses == 'GOVERNMENT':
                restriction = 'restricted'
            if akses.split(':')[0] == 'GOVERNMENT':
                restriction = 'restricted'
            if akses == 'PRIVATE':
                restriction = 'confendential'
            if akses == 'IGSTRATEGIS':
                restriction = 'topsecret'
            print restriction  
            wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
            print wms
            bbox = wms[fi].boundingBoxWGS84
            wb = str(bbox[0])
            sb = str(bbox[1])
            eb = str(bbox[2])
            nb = str(bbox[3])
            bboxwgs84 = wb+','+sb+','+eb+','+nb
            print bboxwgs84
            wmslink = app.config['GEOSERVER_WMS_URL'] + "service=WMS&version=1.1.0&request=GetMap&layers=" + fi + "&styles=&bbox=" + bboxwgs84 + "&width=768&height=768&srs=EPSG:4326&format=application/openlayers"  + "&CQL_FILTER=metadata='" + identifier + "'"
            wfslink = app.config['GEOSERVER_WFS_URL'] + "service=WFS&version=1.0.0&request=GetFeature&typeName=" + fi + "&CQL_FILTER=metadata='" + identifier + "'"
            print wmslink
            print wfslink
            mcf_template = mcf_template.replace('$$rep:fileIdentifier$$', fi)
            # mcf_template = mcf_template.replace('$$rep:individualName$$', individualName)
            # mcf_template = mcf_template.replace('$$rep:organisationName$$', organisationName)
            # mcf_template = mcf_template.replace('$$rep:dateStamp$$', datestamp)
            # mcf_template = mcf_template.replace('$$rep:title$$', title)
            # mcf_template = mcf_template.replace('$$rep:abstract$$', abstract)
            mcf_template = mcf_template.replace('$$rep:security$$', restriction)
            mcf_template = mcf_template.replace('$$rep:secnote$$', akses)
            mcf_template = mcf_template.replace('$$rep:geoserverwms$$', app.config['GEOSERVER_WMS_URL'])
            #mcf_template = mcf_template.replace('$$rep:geoserverwms$$', wmslink)
            mcf_template = mcf_template.replace('$$rep:geoserverwfs$$', app.config['GEOSERVER_WFS_URL'])
            #mcf_template = mcf_template.replace('$$rep:geoserverwfs$$', wfslink)
            # mcf_template = mcf_template.replace('$$rep:wb84$$', wb)
            # mcf_template = mcf_template.replace('$$rep:sb84$$', sb)
            # mcf_template = mcf_template.replace('$$rep:eb84$$', eb)
            # mcf_template = mcf_template.replace('$$rep:nb84$$', nb)
            mcf_template = mcf_template.replace('$$rep:bboxwgs84$$', bboxwgs84)
            rendered_xml = render_template(mcf_template, schema_local=app.config['APP_BASE'] + 'CP-indonesia')
        # print rendered_xml
        except:
            msg = json.dumps({'MSG':'Metadata tidak sesuai standar!'})
        # try:
        # print rendered_xml
        csw = CatalogueServiceWeb(app.config['CSW_URL'])
        cswtrans = csw.transaction(ttype='insert', typename='gmd:MD_Metadata', record=rendered_xml)
        if workspace == 'KUGI':
            metakugi = Metakugi.query.filter_by(identifier=header['pubdata']['identifier']).first()     
            metakugi.published = 'Y'
            db.session.commit()                          
        else:
            metalinks = Metalinks.query.filter_by(identifier=header['pubdata']['identifier']).first()
            metalinks.published = 'Y'
            db.session.commit()
        msg = json.dumps({'MSG':'Publish servis CSW sukses!'})
        # except:
        #     msg = json.dumps({'MSG':'Publish servis CSW gagal!'})
        return Response(msg, mimetype='application/json')

@app.route('/api/pycswRecord/delete', methods=['POST'])
def pycswRecordDelete():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])   
        print header 
        identifier = header['pubdata']['identifier']
        workspace = header['pubdata']['workspace']
        try:
            con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
            con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = con.cursor()
            if workspace == 'KUGI':
                print "WK KUGI"
                sql = "DELETE from metadata WHERE identifier='%s';" % (str(identifier))    
                print sql         
                cur.execute(sql)                
                sqlm = "UPDATE metakugi SET published='N' WHERE identifier='%s';" % (str(identifier))
                cur.execute(sqlm)
            else:
                print "WK OTHERS"
                identifierlink = workspace + ':' + identifier
                sql = "DELETE from metadata WHERE identifier='%s';" % (str(identifierlink))    
                print sql         
                cur.execute(sql)                
                sqlm = "UPDATE metalinks SET published='N' WHERE identifier='%s';" % (str(identifier))
                cur.execute(sqlm)                
            msg = json.dumps({'MSG':'Berhasil unpublish servis CSW!'})
        except:
            msg = json.dumps({'MSG':'Gagal unpublish servis CSW!'})
    return Response(msg, mimetype='application/json')

@app.route('/api/minmetadata', methods=['POST'])
def minmetadata():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        workspace = header['pubdata']['WORKSPACE']
        akses = header['pubdata']['AKSES']
        print akses
        if akses == 'PUBLIC':
            restriction = 'unclassified'
        if akses == 'GOVERNMENT':
            restriction = 'restricted'
        if akses.split(':')[0] == 'GOVERNMENT':
            restriction = 'restricted'
        if akses == 'PRIVATE':
            restriction = 'confendential'
        if akses == 'IGSTRATEGIS':
            restriction = 'topsecret'
        try:
            selectedsimpul = header['pubdata']['SELECTEDSIMPUL']
        except:
            selectedsimpul = ''
        layer_id = header['pubdata']['ID']
        layer_title = urllib2.unquote(header['pubdata']['TITLE'])
        try:
            layer_abstract = urllib2.unquote(header['pubdata']['ABSTRACT'])
        except:
            layer_abstract = layer_title
        print header
        # distro
        info = {}
        sisinfo = db.session.query(Sistem).all()
        for row in sisinfo:
            info[row.key] = row.value
            resp = json.dumps(info)
        distorganisationName = info['organization']
        distdataSetURI = info['url']
        distindividualName = info['organization']
        distpositionName = info['organization']
        distvoice = info['phone']
        distfacsimile = info['fax']
        distdeliveryPoint = info['address']
        distcity = info['city']
        distadministrativeArea = info['administrativearea']
        distpostalCode = info['postalcode']
        distcountry = info['country']
        distelectronicMailAddress = info['email']
        disthoursOfServiceidentifi2 = info['hoursofservice']
        distcontactInstructionsidentifi2 = info['contactinstruction']
        # grup
        group = Group.query.filter_by(name=header['pubdata']['WORKSPACE']).first()
        organisationName = group.name
        dataSetURI = group.url
        individualName = group.organization
        positionName = group.organization
        voice = group.phone
        facsimile = group.fax
        deliveryPoint = group.address
        city = group.city
        administrativeArea = group.administrativearea
        postalCode = group.postalcode
        country = group.country
        electronicMailAddress = group.email
        hoursOfServiceidentifi2 = '09:00 - 15:00 WIB'
        contactInstructionsidentifi2 = 'email/phone'
        fi = workspace + ':' + layer_id
        # template
        with open(cfg.APP_BASE + 'CP-minimal.mcf') as file:
            mcf_minimal = file.read()
        file.close()
        datenow = datetime
        datestamp = datenow.datetime.now().isoformat()
        # template replace
        mcf_minimal = mcf_minimal.replace('$$rep:fileIdentifier$$', fi)
        mcf_minimal = mcf_minimal.replace('$$rep:dateStamp$$', datestamp)
        # ident
        mcf_minimal = mcf_minimal.replace('$$rep:title$$', layer_title)
        mcf_minimal = mcf_minimal.replace('$$rep:abstract$$', layer_abstract)
        mcf_minimal = mcf_minimal.replace('$$rep:keywords$$', layer_title)
        mcf_minimal = mcf_minimal.replace('$$rep:topicCategory$$', 'location')
        mcf_minimal = mcf_minimal.replace('$$rep:publicationDate$$', datestamp)
        mcf_minimal = mcf_minimal.replace('$$rep:feesidentifi7$$', 'N/A')
        mcf_minimal = mcf_minimal.replace('$$rep:organisationNameIdentifi$$', workspace)
        mcf_minimal = mcf_minimal.replace('$$rep:security$$', restriction)
        mcf_minimal = mcf_minimal.replace('$$rep:secnote$$', akses)
        # contact
        mcf_minimal = mcf_minimal.replace('$$rep:organisationName$$', organisationName)
        mcf_minimal = mcf_minimal.replace('$$rep:dataSetURI$$', dataSetURI)
        mcf_minimal = mcf_minimal.replace('$$rep:individualName$$', individualName)
        mcf_minimal = mcf_minimal.replace('$$rep:positionName$$', positionName)
        mcf_minimal = mcf_minimal.replace('$$rep:voice$$', voice)
        mcf_minimal = mcf_minimal.replace('$$rep:facsimile$$', facsimile)
        mcf_minimal = mcf_minimal.replace('$$rep:deliveryPoint$$', deliveryPoint)
        mcf_minimal = mcf_minimal.replace('$$rep:city$$', city)
        mcf_minimal = mcf_minimal.replace('$$rep:administrativeArea$$', administrativeArea)
        mcf_minimal = mcf_minimal.replace('$$rep:postalCode$$', postalCode)
        mcf_minimal = mcf_minimal.replace('$$rep:country$$', country)
        mcf_minimal = mcf_minimal.replace('$$rep:electronicMailAddress$$', electronicMailAddress)
        mcf_minimal = mcf_minimal.replace('$$rep:hoursOfServiceidentifi2$$', hoursOfServiceidentifi2)
        mcf_minimal = mcf_minimal.replace('$$rep:contactInstructionsidentifi2$$', contactInstructionsidentifi2)
        # contact distro
        mcf_minimal = mcf_minimal.replace('$$rep:distorganisationName$$', distorganisationName)
        mcf_minimal = mcf_minimal.replace('$$rep:distdataSetURI$$', distdataSetURI)
        mcf_minimal = mcf_minimal.replace('$$rep:distindividualName$$', distindividualName)
        mcf_minimal = mcf_minimal.replace('$$rep:distpositionName$$', distpositionName)
        mcf_minimal = mcf_minimal.replace('$$rep:distvoice$$', distvoice)
        mcf_minimal = mcf_minimal.replace('$$rep:distfacsimile$$', distfacsimile)
        mcf_minimal = mcf_minimal.replace('$$rep:distdeliveryPoint$$', distdeliveryPoint)
        mcf_minimal = mcf_minimal.replace('$$rep:distcity$$', distcity)
        mcf_minimal = mcf_minimal.replace('$$rep:distadministrativeArea$$', distadministrativeArea)
        mcf_minimal = mcf_minimal.replace('$$rep:distpostalCode$$', distpostalCode)
        mcf_minimal = mcf_minimal.replace('$$rep:distcountry$$', distcountry)
        mcf_minimal = mcf_minimal.replace('$$rep:distelectronicMailAddress$$', distelectronicMailAddress)
        mcf_minimal = mcf_minimal.replace('$$rep:disthoursOfServiceidentifi2$$', disthoursOfServiceidentifi2)
        mcf_minimal = mcf_minimal.replace('$$rep:distcontactInstructionsidentifi2$$', distcontactInstructionsidentifi2) 
        print mcf_minimal 
        # render XML
        rendered_xml = render_template(mcf_minimal, schema_local=app.config['APP_BASE'] + 'CP-indonesia')
        print rendered_xml
        # insert XML to metalinks
        metalinks = Metalinks.query.filter_by(identifier=layer_id).first()
        metalinks.xml = rendered_xml
        metalinks.metatick = 'Y'
        metalinks.akses = akses
        db.session.commit()      
        msg = json.dumps({'MSG':'Metadata minimal disimpan!'})
        return Response(msg, mimetype='application/json')

    
@app.route('/api/generate_wms_thumbnails')
def generate_wms_thumbnails():
    wms = WebMapService(app.config['GEOSERVER_WMS_URL'], version='1.1.1')
    list_layer = wms.contents
    for layer in list_layer:
        bbox = wms[layer].boundingBoxWGS84
        srs = 'EPSG:4326'
        try:
            file = app.config['GEOSERVER_THUMBNAILS'] + layer.split(':')[1] + '.png'
        except:
            file = app.config['GEOSERVER_THUMBNAILS'] + layer + '.png'      
        thumbnail = wms.getmap(layers=[layer],srs=srs,bbox=bbox,size=(300,300),format='image/png',transparent=True)
        outfile = open(file, 'wb')
        outfile.write(thumbnail.read())
        outfile.close()        
    msg = json.dumps({'MSG':'Thumbnail generations finished!'})      
    return Response(msg, mimetype='application/json')

@app.route('/api/describeRecord')
def describe_record():
    described_record = {}
    return Response(described_record, mimetype='application/json')

@app.route('/api/kug_kategori')
def kugi_kategori():
    kugi_kategori = {}
    return Response(kugi_kategori, mimetype='application/json')

@app.route('/api/metalist')
def metalist():
    metalist = {}
    return Response(metalist, mimetype='application/json')

@app.route('/api/fitur_tersedia', methods=['POST'])
def fitur_tersedia():
    fitur_tersedia = {}
    return Response(fitur_tersedia, mimetype='application/json')

@app.route('/api/grupfitur')
def grupfitur():
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
    result = engine.execute("select feature, dataset from a_view_fileidentifier group by feature, dataset")
    try:
        for row in result:
            isi = {}
            print row[0], row[1]
            isi['fitur'] = row[0].strip()
            isi['skema'] = row[1].strip()
            output.append(isi)
        resp = json.dumps(output)
    except:
        resp = json.dumps({'MSG': 'ERROR'})
    return Response(resp, mimetype='application/json')

@app.route('/api/grupfitur/simpan/<string:grup>', methods=['POST'])
def grupfitur_simpan(grup):
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print "Header", header['pubdata']
        rmfitur = Grup_fitur.query.filter_by(groupname=grup).delete()
        db.session.commit()
        for result in header['pubdata']:
            print result['skema'], result['fitur'], result['groupname'], result['skala']
            gf = Grup_fitur()
            gf.groupname = result['groupname']
            gf.fitur = result['fitur']
            gf.skema = result['skema']
            gf.skala = result['skala']
            db.session.add(gf)
        db.session.commit()
    resp = json.dumps({'MSG': 'Sukses disimpan!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/grupfitur/<string:grup>')
def grupfitur_q(grup):
    res = Grup_fitur.query.filter_by(groupname=grup).with_entities(Grup_fitur.groupname, Grup_fitur.fitur, Grup_fitur.skema, Grup_fitur.skala)
    result = Grup_fiturSchema(many=True)
    output = result.dump(res)
    return json.dumps(output.data)    

@app.route('/api/kodesimpul')
def kodesimpul():
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    result = engine.execute("select region_cod, region_nam from kode_simpul group by region_cod, region_nam")
    try:
        for row in result:
            isi = {}
            # print row[0], row[1]
            isi = row[0].strip() + ', ' + row[1].strip()
            output.append(isi)
        resp = json.dumps(output)
    except:
        resp = json.dumps({'MSG': 'ERROR'})
    return Response(resp, mimetype='application/json')      

@app.route('/api/kodesimpulext')
def kodesimpulext():
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    result = engine.execute("select region_cod, region_nam, \"4326_minx\", \"4326_minx\", \"4326_maxx\", \"4326_maxy\", c_4326_x, c_4326_y from kode_simpul group by region_cod, region_nam, \"4326_minx\", \"4326_minx\", \"4326_maxx\", \"4326_maxy\", c_4326_x, c_4326_y")
    try:
        for row in result:
            isi = {}
            isi = row[0].strip() + ', ' + row[1].strip() + ', ' + str(row[6]) + ', ' + str(row[7])
            output.append(isi)
        resp = json.dumps(output)
    except:
        resp = json.dumps({'MSG': 'ERROR'})
    return Response(resp, mimetype='application/json')          

@app.route('/api/kodeepsg', methods=['GET'])
def kodeepsg():
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    result = engine.execute("select kode, keterangan from kode_epsg")
    try:
        for row in result:
            isi = {}
            # print row[0], row[1]
            isi = row[0].strip() + ', ' + row[1].strip()
            output.append(isi)
        resp = json.dumps(output)
    except:
        resp = json.dumps({'MSG': 'ERROR'})
    return Response(stream_with_context(resp), mimetype='application/json')         

@app.route('/api/kugiappenddata', methods=['POST'])
def kugiappeddata():
    if request.method == 'POST':
        skema = request.args.get('schema')
        fitur = request.args.get('fitur')
        skala = request.args.get('skala')
        user = request.args.get('USER')
        grup = request.args.get('GRUP')        
        print skema, fitur, skala
        # print 'User:',user, 'Grup:', grup
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Tidak ada berkas dipilih'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_file(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Tipe tidak diperkenankan'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            unzip(filename,filename)
            for f in app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]:
                path, ext = os.path.splitext(f)
                if ext.isupper():
                    os.rename(f, path + ext.lower())
            for berkas in os.listdir(app.config['UPLOAD_FOLDER'] + '/' + filename.split('.')[0]):
                if berkas.endswith(".tif") or berkas.endswith(".TIF") or berkas.endswith(".tiff") or berkas.endswith(".TIFF"):
                    print "Filename: " + filename.split('.')[0]
                    populate = populateRS(filename.split('.')[0])
                    lid = populate[2]
                    SEPSG = populate[1].split(':')[1]
                    resp = json.dumps({'RTN': filename, 'MSG': 'RASTER Upload Success! Proyeksi terdeteksi: ' + populate[1], 'EPSG': populate[1], 'SEPSG': SEPSG, 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'USER': user, 'GRUP': grup, 'LID': lid.lower().replace('-','_')})
                    return Response(resp, mimetype='application/json')                    
                if berkas.endswith(".shp") or berkas.endswith(".SHP"):
                    shapefile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '/' + filename.split('.')[0] + '.shp'
                    dbf = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '/' + filename.split('.')[0] + '.dbf'
                    res_iden = get_iden_unik(dbf)
                    if res_iden == [''] or res_iden == []:
                        resp = json.dumps({'RTN': False, 'MSG': 'Error, Field Metadata Kosong/Tidak Ada!'})
                        return Response(resp, mimetype='application/json')
                        abort(405)
                    res_srsId = get_srsId(dbf)
                    if res_srsId == [''] or res_srsId == []:
                        resp = json.dumps({'RTN': False, 'MSG': 'Error, Field SRS_ID Kosong/Tidak Ada!'})
                        return Response(resp, mimetype='application/json')
                        abort(405) 
                    res_fcode = get_fcode(dbf)       
                    if res_fcode == [''] or res_fcode == []:
                        resp = json.dumps({'RTN': False, 'MSG': 'Error, Field FCODE Kosong/Tidak Ada!'})
                        return Response(resp, mimetype='application/json')
                        abort(405)         
                    else:
                        fcode_cek = cek_fcode(skema, fitur) 

                        print fcode_cek

                        print str(res_fcode[0])


                        print "CODE: FCODE, CEK:", str(res_fcode[0]), fcode_cek            
                        if fcode_cek !=  str(res_fcode[0]):
                            resp = json.dumps({'RTN': False, 'MSG': 'Error, Field FCODE Tidak Sesuai, cek data dengan dokumen KUGI!'})
                            return Response(resp, mimetype='application/json')
                            abort(405)  
                    print "SRS:", res_srsId                
                    print "IDEN:", res_iden
                    print "FCODE:", res_fcode
                    print "Shapefile: " + shapefile
                    if os.path.exists(shapefile):
                        
                        print "File SHP OK"
                        print filename
                        print grup + '_DEV'
                        print skema
                        print fitur
                        print skala
                        print str(res_fcode[0])
                        
                        populate = populateKUGI(filename, grup + '_DEV', skema, fitur, skala, str(res_fcode[0]))
                        print populate
                        if populate[5] == False:
                            resp = json.dumps({'RTN': False, 'MSG': 'Error, Tipe Geometri tidak cocok!'})
                            return Response(resp, mimetype='application/json')
                            abort(405)  
                        refresh_dbmetafieldview(grup + '_DEV')
                        lid = populate[2]+'-'+populate[3]
                        SEPSG = populate[1].split(':')[1]
                        resp = json.dumps({'RTN': filename, 'MSG': 'Vector Upload Sukses!' + populate[0], 'EPSG': populate[1], 'SEPSG': SEPSG, 'ID': populate[2], 'UUID': populate[3], 'TIPE': populate[4], 'OGR': populate[5], 'USER': user, 'GRUP': grup, 'IDEN': res_iden, 'LID': lid.lower().replace('-','_')})
                        for iden in res_iden:
                            try:
                                if Metakugi_dev.query.filter_by(identifier=iden).first():
                                    pass
                                else:
                                    metakugi_dev = Metakugi_dev(identifier=iden)
                                    metakugi_dev.skema = skema
                                    metakugi_dev.fitur = fitur
                                    metakugi_dev.workspace = grup
                                    # metakugi_dev.xml = isixml
                                    # metakugi_dev.metatick = 'Y'
                                    # metakugi_dev.akses = request.args['akses']
                                    db.session.add(metakugi_dev)
                            except:
                                pass
                        try:
                            db.session.commit()
                        except:
                            pass                        
                        return Response(resp, mimetype='application/json')
                    else:
                        resp = json.dumps({'RTN': 'ERR', 'MSG': 'Tidak ada berkas SHAPE terdeteksi!'})
                        return Response(resp, status=405, mimetype='application/json')
        resp = json.dumps({'RTN': 'ERR', 'MSG': 'Terjadi kesalahan'})
        return Response(resp, mimetype='application/json')

@app.route('/api/refresh_dbmetaview', methods=['POST'])
def refresh_dbmetaview():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print "Header", header['pubdata'] 
        dbkugi = header['pubdata']['dbkugi']
        # dbkugi = request.args.get('dbkugi')
        try:
            refresh_dbmetafieldview(dbkugi)
            resp = json.dumps({'RTN': 'Success', 'MSG': 'Refreshed!'})
        except:
            resp = json.dumps({'RTN': 'Error', 'MSG': 'Terjadi Kesalahan!'})      
    return Response(resp, mimetype='application/json')         

@app.route('/api/delete_spatial_records', methods=['POST'])
def deletespatialrecords():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        print "Header", header['pubdata'] 
        skema = header['pubdata']['skema']
        fitur = header['pubdata']['fitur']
        identifier = header['pubdata']['identifier']
        db = header['pubdata']['db']
        grup = header['pubdata']['grup']
        if db == 'dbdev':
            db = grup + '_DEV'
            metadb = 'dev'
        if db == 'dbprod':
            metadb = 'prod'
        if db == 'dbpub':
            metadb = 'pub'
        try:
            delete_spatial_records(skema,fitur,identifier,db)
            refresh_dbmetafieldview(db)
            if db == 'dbpub':
                delete_metakugi(identifier)
            else:
                delete_metakugi_db(metadb,identifier)
            resp = json.dumps({'RTN': 'Success', 'MSG': 'Data berhasi dihapus!'})
        except:
            resp = json.dumps({'RTN': 'Error', 'MSG': 'Terjadi Kesalahan!'})      
    return Response(resp, mimetype='application/json')    

@app.route('/api/gruponlyfitur/<string:grup>')
def gruponlyfitur(grup):
    output = {}
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    result_skala = engine.execute("select skala from group_features where groupname='%s' group by skala" % str(grup))
    for skala in result_skala:
        print "SKALA", skala
        sql = "select skema from group_features where skala = '%s' and groupname = '%s' group by skema" % (str(skala[0]), str(grup))
        print sql
        result_kategori = engine.execute(sql)
        # print skala[0]
        output[skala[0]] = {}
        for kategori in result_kategori:
            # print "\t", kategori[0]
            sql ="select fitur from group_features where skala = '%s' and skema = '%s' and groupname = '%s' group by fitur" % (str(skala[0]), str(kategori[0]), str(grup))
            result_fitur = engine.execute(sql)
            output[skala[0]][kategori[0]] = []
            for fitur in result_fitur:
                # print "\t\t", fitur[0]
                output[skala[0]][kategori[0]].append(fitur[0])
    return Response(json.dumps(output), mimetype='application/json')

@app.route('/api/dbdevfeature')
def dbdevfeature():
    output = {}
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    result_skala = engine.execute("select skala from a_view_feature group by skala")
    for skala in result_skala:
        print "SKALA", skala
        result_kategori = engine.execute("select dataset from a_view_feature where skala = %s group by dataset" , skala)
        # print skala[0]
        output[skala[0]] = {}
        for kategori in result_kategori:
            # print "\t", kategori[0]
            sql ="select kategori from a_view_feature where skala = '%s' and dataset = '%s' group by kategori" % (str(skala[0]), str(kategori[0]))
            result_fitur = engine.execute(sql)
            output[skala[0]][kategori[0]] = []
            for fitur in result_fitur:
                # print "\t\t", fitur[0]
                output[skala[0]][kategori[0]].append(fitur[0])
    return Response(json.dumps(output), mimetype='application/json')

@app.route('/api/dbkugilist/<string:kategori>')
def dbkugilist(kategori):
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    result_sql = engine.execute("select feature from a_view_feature where dataset=%s", kategori)
    for fitur in result_sql:
        print "Fitur:", fitur[0]
        output.append(fitur[0])
    return Response(json.dumps(output), mimetype='application/json')

@app.route('/api/dbdevisifeature')
def dbdevisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbdev'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/dbdevisifeature/<string:grup>')
def dbdevisifeature_grup(grup):
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_DATASTORE'] + '%s_DEV' % str(grup))
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        sql = "select * from a_view_fileidentifier where fileidentifier='%s'" % str(row['fileidentifier'])
        con = psycopg2.connect(dbname='palapa_prod', user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()  
        cur.execute(sql)     
        try:
            if cur.fetchone()[0] is not None:
                output['inprod'] = True
        except:
            output['inprod'] = False
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')    

@app.route('/api/dbprodisifeature')
def dbprodisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbprod'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        sql = "select * from a_view_fileidentifier where fileidentifier='%s'" % str(row['fileidentifier'])
        con = psycopg2.connect(dbname='palapa_pub', user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()  
        cur.execute(sql)     
        try:
            if cur.fetchone()[0] is not None:
                output['inpub'] = True
        except:
            output['inpub'] = False   
        con.close()  
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/dbpubisifeature')
def dbpubisifeature():
    output = {}
    outputs = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
    result = engine.execute("select * from a_view_fileidentifier")    
    for row in result:
        output['id'] = row['id']
        output['feature'] = row['feature'].strip()
        output['iddataset'] = row['iddataset']
        output['idkategori'] = row['idkategori']
        output['idskala'] = row['idskala']
        output['dataset'] = row['dataset']
        output['kategori'] = row['kategori']
        output['tipe'] = row['tipe']
        output['alias'] = row['alias']
        output['skala'] = row['skala']
        output['identifier'] = row['fileidentifier']
        outputs.append(output)
        output = {}
    return Response(json.dumps(outputs), mimetype='application/json')

@app.route('/api/kopitable', methods=['POST'])
def kopitable():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
        source_schema = header['pubdata']['dataset']
        source_table = header['pubdata']['feature']
        dest_schema = header['pubdata']['dataset']
        dest_table = header['pubdata']['feature']
        identifier = header['pubdata']['identifier']
        source_db = header['pubdata']['source_db']
        dest_db = header['pubdata']['dest_db']
        try:
            execute = pgis2pgis(source_db, source_schema, source_table, dest_db, dest_schema, dest_table, identifier)
            refresh_dbmetafieldview('dbprod')
            refresh_dbmetafieldview('dbpub')
            try:
                con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
                con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                cur = con.cursor()  
                if dest_db == 'palapa_prod':
                    if Metakugi_prod.query.filter_by(identifier=identifier).first():
                        pass
                    else:
                        sql_user = "INSERT INTO metakugi_prod (SELECT * FROM metakugi_dev WHERE identifier='%s');" % str(identifier)
                        cur.execute(sql_user)   
                if dest_db == 'palapa_pub':
                    if Metakugi.query.filter_by(identifier=identifier).first():
                        pass
                    else:
                        sql_user = "INSERT INTO metakugi (SELECT * FROM metakugi_prod WHERE identifier='%s');" % str(identifier)
                        cur.execute(sql_user)   
                        sql_alter = "UPDATE metakugi SET workspace='KUGI' WHERE identifier='%s';" % str(identifier)
                        cur.execute(sql_alter)
                con.close()
            except:
                pass
            resp = json.dumps({'RTN': 'OK', 'MSG': 'Migrasi dataset Sukses!'})
        except:
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Migrasi dataset Gagal!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/cekmeta/<string:table>/<string:identifier>')
def cekmeta(table, identifier):
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    sql = "SELECT identifier FROM %s WHERE identifier='%s'" % (table, identifier)
    result = engine.execute(sql)
    if result.rowcount > 0:
        resp = json.dumps({ 'MSG': True })
    else:
        resp = json.dumps({ 'MSG': False })
    return Response(resp, mimetype='application/json')       

@app.route('/api/cekmeta/<string:table>')
def cekmeta_table(table):
    output = []
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['services'])
    sql = "SELECT identifier FROM %s" % (table)
    result = engine.execute(sql)
    for row in result:
        output.append(row[0])
    resp = json.dumps(output)
    return Response(resp, mimetype='application/json')           

@app.route('/api/meta/view')
# @auth.login_required
def meta_view():
    metalink = Metalinks.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')    

@app.route('/api/metakugi/view')
# @auth.login_required
def metakugi_view():
    metalink = Metakugi.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')        

@app.route('/api/metakugi_dev/view')
# @auth.login_required
def metakugi_dev_view():
    metalink = Metakugi_dev.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')     

@app.route('/api/metakugi_prod/view')
# @auth.login_required
def metakugi_prod_view():
    metalink = Metakugi_prod.query.filter_by(identifier=request.args['identifier']).first()
    xml = metalink.xml
    return Response(xml, mimetype='application/xml')         

@app.route('/api/meta/list')
# @auth.login_required
def meta_list():
    metalist = Metalinks.query.with_entities(Metalinks.workspace, Metalinks.identifier, Metalinks.metatick, Metalinks.published, Metalinks.akses)
    metalinks = MetalinksSchema(many=True)
    output = metalinks.dump(metalist)
    return json.dumps(output.data)    

@app.route('/api/metakugi/list')
# @auth.login_required
def kugi_list():
    metalist = Metakugi.query.with_entities(Metakugi.skema, Metakugi.fitur, Metakugi.workspace, Metakugi.identifier, Metakugi.metatick, Metakugi.published, Metakugi.akses, Metakugi.tipe)
    metalinks = MetakugiSchema(many=True)
    output = metalinks.dump(metalist)
    return json.dumps(output.data)    


@app.route('/api/meta/link', methods=['POST'])
# @auth.login_required
def add_link():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        print 'Param:', request.args['identifier'], request.args['akses']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_xml(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_xml(file.filename):
            try:    
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                print "Filename: " + filename.split('.')[0]
                xmlfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.xml'
                print "XML: " + xmlfile
                if os.path.exists(xmlfile):
                    print "File XML OK"
                    # catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    xml = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    try:
                        with open (xmlfile, 'r') as thefile:
                            isixml = thefile.read()
                        metalinks = Metalinks.query.filter_by(identifier=request.args['identifier']).first()
                        metalinks.xml = isixml
                        metalinks.metatick = 'Y'
                        metalinks.akses = request.args['akses']
                        # db.session.add(metalinks)
                        db.session.commit()
                        # catalog.create_style(filename.split('.')[0], xml.read()) 
                        resp = json.dumps({'RTN': True, 'MSG': 'Upload metadata sukses!'})
                    except:
                        resp = json.dumps({'RTN': False, 'MSG': 'Error, metadata dengan identifier yang sama sudah ada!'})
                else:
                    resp = json.dumps({'RTN': False, 'MSG': 'No SHAPE file!'})
            except:
                resp = json.dumps({'RTN': False, 'MSG': 'Upload metadata gagal!'})
        return Response(resp, mimetype='application/json')    
    # return jsonify({'RTN': 'Hello!'})

@app.route('/api/metakugi/link/<string:dbase>', methods=['POST'])
# @auth.login_required
def add_kugilink(dbase):
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        print 'Param:', request.args['identifier'], request.args['akses']
        iden = str(request.args['identifier'])
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_xml(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_xml(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            print "Filename: " + filename.split('.')[0]
            xmlfile = app.config['UPLOAD_FOLDER'] + filename.split('.')[0] + '.xml'
            print "XML: " + xmlfile
            if os.path.exists(xmlfile):
                print "File XML OK"
                # catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                xml = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                try:
                    with open (xmlfile, 'r') as thefile:
                        isixml = thefile.read()
                    if dbase == 'dev':
                        metakugi_dev = Metakugi_dev.query.filter_by(identifier=iden).first()
                        if metakugi_dev is None:
                            metakugi_dev = Metakugi_dev(identifier=iden)
                            metakugi_dev.xml = isixml
                            metakugi_dev.metatick = 'Y'
                            metakugi_dev.akses = str(request.args['akses'])
                            metakugi_dev.workspace = str(request.args['workspace'])
                            metakugi_dev.skema = str(request.args['skema'])
                            metakugi_dev.fitur = str(request.args['fitur'])
                            db.session.add(metakugi_dev)
                        else:
                            metakugi_dev.xml = isixml
                            metakugi_dev.metatick = 'Y'
                            metakugi_dev.akses = str(request.args['akses'])
                            metakugi_dev.workspace = str(request.args['workspace'])
                            metakugi_dev.skema = str(request.args['skema'])
                            metakugi_dev.fitur = str(request.args['fitur'])
                    if dbase == 'prod':
                        metakugi_prod = Metakugi_prod.query.filter_by(identifier=iden).first()
                        if metakugi_prod is None:
                            metakugi_prod = Metakugi_prod(identifier=iden)
                            metakugi_prod.xml = isixml
                            metakugi_prod.metatick = 'Y'
                            metakugi_prod.akses = str(request.args['akses'])
                            metakugi_prod.workspace = str(request.args['workspace'])
                            metakugi_prod.skema = str(request.args['skema'])
                            metakugi_prod.fitur = str(request.args['fitur'])
                            db.session.add(metakugi_prod)
                        else:
                            metakugi_prod.xml = isixml
                            metakugi_prod.metatick = 'Y'
                            metakugi_prod.akses = str(request.args['akses'])
                            metakugi_prod.workspace = str(request.args['workspace'])
                            metakugi_prod.skema = str(request.args['skema'])
                            metakugi_prod.fitur = str(request.args['fitur'])
                    if dbase == 'pub':
                        metakugi = Metakugi.query.filter_by(identifier=iden).first()
                        if metakugi is None:
                            metakugi = Metakugi(identifier=iden)
                            metakugi.xml = isixml
                            metakugi.metatick = 'Y'
                            metakugi.akses = str(request.args['akses'])
                            metakugi.workspace = 'KUGI'
                            metakugi.skema = str(request.args['skema'])
                            metakugi.fitur = str(request.args['fitur'])
                            db.session.add(metakugi)
                        else:
                            metakugi.xml = isixml
                            metakugi.metatick = 'Y'
                            metakugi.akses = str(request.args['akses'])   
                            metakugi.workspace = 'KUGI'
                            metakugi.skema = str(request.args['skema'])
                            metakugi.fitur = str(request.args['fitur'])                                 
                    # db.session.add(metalinks)
                    db.session.commit()
                # catalog.create_style(filename.split('.')[0], xml.read()) 
                    resp = json.dumps({'RTN': True, 'MSG': 'Upload metadata sukses!'})
                except:
                    resp = json.dumps({'RTN': True, 'MSG': 'Upload metadata sukses!'})
                    # resp = json.dumps({'RTN': False, 'MSG': 'Error, metadata dengan identifier yang sama sudah ada!'})
            else:
                resp = json.dumps({'RTN': False, 'MSG': 'Upload metadata gagal!'})
        return Response(resp, mimetype='application/json')    
    # return jsonify({'RTN': 'Hello!'})

@app.route('/api/front_layers/add', methods=['POST'])
def add_front_layers():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])   
        print "Header:", header['pubdata']
        content = header['pubdata']
        try:
            Front_layers.query.delete()
            for row in content:
                # print row
                print row['id'],row['layer_nativename'],row['layer_title'],row['aktif']
                if row['pilih'] == True:
                    front_layer_row = Front_layers(id=row['id'])
                    front_layer_row.layer_nativename = row['layer_nativename']
                    front_layer_row.layer_title = urllib2.unquote(row['layer_title'])
                    front_layer_row.aktif = row['aktif']
                    db.session.add(front_layer_row)
                    db.session.commit()
                resp = json.dumps({'RTN': True, 'MSG': 'Sukses disimpan'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Gagal disimpan!'})
        # resp = json.dumps({'RTN': False, 'MSG': 'TEST'})
        return Response(resp, mimetype='application/json')           

@app.route('/api/front_layers/truncate', methods=['POST'])
def truncate_front_layers():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])   
        print "Header:", header['pubdata']
        try:
            con = psycopg2.connect(dbname=app.config['DATASTORE_DB'], user=app.config['DATASTORE_USER'], host=app.config['DATASTORE_HOST'], password=app.config['DATASTORE_PASS'])
            con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = con.cursor()
            sql = "TRUNCATE table front_layers;"   
            print sql         
            cur.execute(sql)       
            cur.close()         
            resp = json.dumps({'RTN': True, 'MSG': 'Tabel dikosongkan.'})
        except:
            resp = json.dumps({'RTN': False, 'MSG': 'Tabel gagal dikosongkan.'})
    return Response(resp, mimetype='application/json')           

@app.route('/api/front_layers')
def front_layers():
    front_layers_list = Front_layers.query.with_entities(Front_layers.id, Front_layers.layer_nativename, Front_layers.layer_title, Front_layers.aktif)
    front_layers = Front_layersSchema(many=True)
    output = front_layers.dump(front_layers_list)
    return Response(json.dumps(output.data), mimetype='application/json')   

@app.route('/api/savetable/<string:db>/<string:skema>/<string:fitur>/<string:identifier>')
def savetable(db, skema, fitur, identifier):
    link = save_table(db, skema, fitur, identifier)
    filename = fitur + '_' + identifier + '.gml'
    with open(link, 'r') as file:
        gml = file.read()
    response = Response(stream_with_context(gml), mimetype='application/gml+xml')
    response.headers['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response

@app.route('/api/proxy', methods=['POST','GET'])
def crossdom():
    reply = proxypy.get(request.query_string)
    # print request.query_string
    # print "REPLY:", reply
    proxy = json.loads(reply)
    result = proxy['content']
    if request.method == 'POST':
        print "POST", request.query_string
        print "DATA", request.data
        print "HEADER", request.headers
        data = request.data
        reply = proxypy.post(request.query_string,request.data,request.headers)
        proxy = json.loads(reply)
        result = proxy['content']
    return Response(result,status=200, mimetype='text/plain')

@app.route('/api/docs/link', methods=['POST'])
# @auth.login_required
def docs_link():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            print 'No file part' 
            resp = json.dumps({'MSG': 'No file part'})
            return Response(resp, mimetype='application/json')
        file = request.files['file']
        print file
        # print 'Param:', request.args['identifier']
        # if user does not select file, browser also
        # submit a empty part without filename
        if file.filename == '':
            print 'No selected file' 
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'No selected file'})
            return Response(resp, status=405, mimetype='application/json')
        if not allowed_docs(file.filename):
            resp = json.dumps({'RTN': 'ERR', 'MSG': 'Type not allowed'})
            return Response(resp, status=405, mimetype='application/json')
        if file and allowed_docs(file.filename):
            print "F:", secure_filename(file.filename)
            try:    
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['DOCUMENTS_FOLDER'], filename))
                print "Filename: " + filename.split('.')[0]
                docsfile = app.config['DOCUMENTS_FOLDER'] + filename
                print "docs: " + docsfile
                if os.path.exists(docsfile):
                    print "File DOCS OK"
                    # catalog = Catalog(app.config['GEOSERVER_REST_URL'], app.config['GEOSERVER_USER'], app.config['GEOSERVER_PASS'])
                    # xml = open(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    # try:
                    #     with open (docsfile, 'r') as thefile:
                    #         isixml = thefile.read()
                    #     metalinks = Metalinks.query.filter_by(identifier=request.args['identifier']).first()
                    #     metalinks.xml = isixml
                    #     metalinks.metatick = 'Y'
                    #     metalinks.akses = request.args['akses']
                    #     # db.session.add(metalinks)
                    #     db.session.commit()
                    #     # catalog.create_style(filename.split('.')[0], xml.read()) 
                    resp = json.dumps({'RTN': True, 'MSG': 'Upload berkas pendukung sukses!'})
                    # except:
                    #     resp = json.dumps({'RTN': False, 'MSG': 'Error, metadata dengan identifier yang sama sudah ada!'})
                else:
                    resp = json.dumps({'RTN': False, 'MSG': 'No DOCs file!'})
                    return Response(resp, status=405, mimetype='application/json')
            except:
                resp = json.dumps({'RTN': False, 'MSG': 'Upload berkas pendukung gagal!'})
        return Response(resp, mimetype='application/json')    
    # return jsonify({'RTN': 'Hello!'})

@app.route('/api/frontendtheme')
def frontendtheme():
    frontendtheme = {}
    sisinfo = db.session.query(FrontendTheme).all()
    for row in sisinfo:
        #print row.key, row.value
        frontendtheme[row.key] = row.value
        resp = json.dumps(frontendtheme)
    return Response(resp, mimetype='application/json')

@app.route('/api/setfrontendtheme', methods=['POST'])
def setfrontendtheme():
    if request.method == 'POST':
        header = json.loads(urllib2.unquote(request.data).split('=')[1])
    print header
    judul_situs = urllib2.unquote(header['pubdata']['judul_situs'])
    logo_situs = urllib2.unquote(header['pubdata']['logo_situs'])
    berkas_gambar_1 = urllib2.unquote(header['pubdata']['berkas_gambar_1'])
    berkas_gambar_2 = urllib2.unquote(header['pubdata']['berkas_gambar_2'])
    keterangan_gambar_1 = urllib2.unquote(header['pubdata']['keterangan_gambar_1'])
    keterangan_gambar_2 = urllib2.unquote(header['pubdata']['keterangan_gambar_2'])
    judul_headline = urllib2.unquote(header['pubdata']['judul_headline'])
    keterangan_headline = urllib2.unquote(header['pubdata']['keterangan_headline'])
    judul_fitur = urllib2.unquote(header['pubdata']['judul_fitur'])
    keterangan_fitur = urllib2.unquote(header['pubdata']['keterangan_fitur'])
    tipe_tema = urllib2.unquote(header['pubdata']['tipe_tema'])
    c_x = header['pubdata']['c_x']
    c_y = header['pubdata']['c_y']
    c_zoom = header['pubdata']['c_zoom']
    r_judul_situs = FrontendTheme.query.filter_by(key='judul_situs').first()
    r_logo_situs = FrontendTheme.query.filter_by(key='logo_situs').first()
    r_berkas_gambar_1 = FrontendTheme.query.filter_by(key='berkas_gambar_1').first()
    r_berkas_gambar_2 = FrontendTheme.query.filter_by(key='berkas_gambar_2').first()
    r_keterangan_gambar_1 = FrontendTheme.query.filter_by(key='keterangan_gambar_1').first()
    r_keterangan_gambar_2 = FrontendTheme.query.filter_by(key='keterangan_gambar_2').first()
    r_judul_headline = FrontendTheme.query.filter_by(key='judul_headline').first()
    r_keterangan_headline = FrontendTheme.query.filter_by(key='keterangan_headline').first()
    r_judul_fitur = FrontendTheme.query.filter_by(key='judul_fitur').first()
    r_keterangan_fitur = FrontendTheme.query.filter_by(key='keterangan_fitur').first()
    r_tipe_tema = FrontendTheme.query.filter_by(key='tipe_tema').first()
    r_c_x = FrontendTheme.query.filter_by(key='c_x').first()
    r_c_y = FrontendTheme.query.filter_by(key='c_y').first()
    r_c_zoom = FrontendTheme.query.filter_by(key='c_zoom').first()
    r_judul_situs.value = judul_situs
    r_logo_situs.value = logo_situs
    r_berkas_gambar_1.value = berkas_gambar_1
    r_berkas_gambar_2.value = berkas_gambar_2
    r_keterangan_gambar_1.value = keterangan_gambar_1
    r_keterangan_gambar_2.value = keterangan_gambar_2
    r_judul_headline.value = judul_headline
    r_keterangan_headline.value = keterangan_headline
    r_judul_fitur.value = judul_fitur
    r_keterangan_fitur.value = keterangan_fitur
    r_tipe_tema.value = tipe_tema
    r_c_x.value = c_x
    r_c_y.value = c_y
    r_c_zoom.value = c_zoom
    db.session.commit()	
    if tipe_tema == '1':
        with open(app.config['PALAPA_FOLDER'] + 'templates/index.html') as berkas_index:
            template_index = berkas_index.read()
        berkas_index.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/cari.html') as berkas_cari:
            template_cari = berkas_cari.read()
        berkas_cari.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/jelajah.html') as berkas_jelajah:
            template_jelajah = berkas_jelajah.read()
        berkas_jelajah.close()
    if tipe_tema == '2':
        with open(app.config['PALAPA_FOLDER'] + 'templates/index3.html') as berkas_index:
            template_index = berkas_index.read()
        berkas_index.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/cari3.html') as berkas_cari:
            template_cari = berkas_cari.read()
        berkas_cari.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/jelajah3.html') as berkas_jelajah:
            template_jelajah = berkas_jelajah.read()
        berkas_jelajah.close()
    if tipe_tema == '3':
        with open(app.config['PALAPA_FOLDER'] + 'templates/index4.html') as berkas_index:
            template_index = berkas_index.read()
        berkas_index.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/cari4.html') as berkas_cari:
            template_cari = berkas_cari.read()
        berkas_cari.close()
        with open(app.config['PALAPA_FOLDER'] + 'templates/jelajah4.html') as berkas_jelajah:
            template_jelajah = berkas_jelajah.read()
        berkas_jelajah.close()
    with open(app.config['PALAPA_FOLDER'] + 'templates/cfg.js') as berkas_cfgol:
        template_cfgol = berkas_cfgol.read()
    berkas_cfgol.close()
   
    cap_depan = judul_situs[:1].encode('ascii', 'ignore')
    cap_belakang = judul_situs[1:].encode('ascii', 'ignore')
   
    logo_path = 'image/' + logo_situs
    gambar1_path = 'image/' + berkas_gambar_1
    gambar2_path = 'image/' + berkas_gambar_2

    logo_path = logo_path.encode('ascii', 'ignore')
    gambar1_path = gambar1_path.encode('ascii', 'ignore')
    gambar2_path = gambar2_path.encode('ascii', 'ignore')

    info = {}
    sisinfo = db.session.query(Sistem).all()
    for row in sisinfo:
        print row.key, row.value
        info[row.key] = row.value
    template_index = template_index.replace('$$rep:captitledepan$$',cap_depan)
    template_index = template_index.replace('$$rep:titledepan$$',cap_belakang)
    template_index = template_index.replace('$$rep:logositus$$',logo_path)
    template_index = template_index.replace('$$rep:gambar1$$',gambar1_path)
    template_index = template_index.replace('$$rep:captiongambar1$$',keterangan_gambar_1)
    template_index = template_index.replace('$$rep:gambar2$$',gambar2_path)
    template_index = template_index.replace('$$rep:captiongambar2$$',keterangan_gambar_2)
    template_index = template_index.replace('$$rep:innertitle$$',judul_headline)
    template_index = template_index.replace('$$rep:innerdesc$$',keterangan_headline)
    template_index = template_index.replace('$$rep:innertitle2$$',judul_fitur)
    template_index = template_index.replace('$$rep:innerdesc2$$',keterangan_fitur)
    template_index = template_index.replace('$$rep:organization$$',info['organization'])
    template_index = template_index.replace('$$rep:address$$',info['address'])
    template_index = template_index.replace('$$rep:email$$',info['email'])
    template_index = template_index.replace('$$rep:voice$$',info['phone'])
    template_index = template_index.replace('$$rep:fax$$',info['fax'])
    if os.path.isfile(app.config['PALAPA_FOLDER'] + 'index.html'):
        os.remove(app.config['PALAPA_FOLDER'] + 'index.html')
    berkas_index_write = open(app.config['PALAPA_FOLDER'] + 'index.html', 'a')
    berkas_index_write.write(template_index)
    berkas_index_write.close()
    template_jelajah = template_jelajah.replace('$$rep:captitledepan$$',cap_depan)
    template_jelajah = template_jelajah.replace('$$rep:titledepan$$',cap_belakang)
    template_jelajah = template_jelajah.replace('$$rep:logositus$$',logo_path)	
    if os.path.isfile(app.config['PALAPA_FOLDER'] + 'jelajah.html'):
        os.remove(app.config['PALAPA_FOLDER'] + 'jelajah.html')
    berkas_jelajah_write = open(app.config['PALAPA_FOLDER'] + 'jelajah.html', 'a')
    berkas_jelajah_write.write(template_jelajah)
    berkas_jelajah_write.close()
    template_cari = template_cari.replace('$$rep:captitledepan$$',cap_depan)
    template_cari = template_cari.replace('$$rep:titledepan$$',cap_belakang)
    template_cari = template_cari.replace('$$rep:logositus$$',logo_path)		
    if os.path.isfile(app.config['PALAPA_FOLDER'] + 'cari.html'):
        os.remove(app.config['PALAPA_FOLDER'] + 'cari.html')
    berkas_cari_write = open(app.config['PALAPA_FOLDER'] + 'cari.html', 'a')
    berkas_cari_write.write(template_cari)
    berkas_cari_write.close()
    template_cfgol = template_cfgol.replace('$$rep:c_x$$', str(c_x))
    template_cfgol = template_cfgol.replace('$$rep:c_y$$', str(c_y))
    template_cfgol = template_cfgol.replace('$$rep:c_zoom$$', str(c_zoom))		
    if os.path.isfile(app.config['PALAPA_FOLDER'] + 'js/cfg.js'):
        os.remove(app.config['PALAPA_FOLDER'] + 'js/cfg.js')
    berkas_cfgol_write = open(app.config['PALAPA_FOLDER'] + 'js/cfg.js', 'a')
    berkas_cfgol_write.write(template_cfgol)
    berkas_cfgol_write.close()
    msg = json.dumps({'Result': True, 'MSG':'Data sukses disimpan!'})
    return Response(msg, mimetype='application/json')

@app.route('/api/setfrontend/uploadlogo', methods=['POST'])
def uploadlogo():
    if request.method == 'POST':
        if 'file' not in request.files:
            resp = json.dumps({'Result': False, 'MSG': 'Error'})
            abort(400)
    file = request.files['file']
    print file
    if file.filename == '':
        resp = json.dumps({'Result': False, 'MSG': 'Error, no file!'})
        return Response(resp, status=405, mimetype='application/json')
    if file:
        try:
            filename = secure_filename(file.filename)
            print os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename)
            file.save(os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename))
            resp = json.dumps({'Result': True, 'MSG': 'Upload sukses!', 'VAL': filename})
        except:
            resp = json.dumps({'Result': False, 'MSG': 'Upload gagal!', 'VAL': filename})
    return Response(resp, mimetype='application/json')

@app.route('/api/setfrontend/uploadgambar1', methods=['POST'])
def uploadgambar1():
    if request.method == 'POST':
        if 'file' not in request.files:
            resp = json.dumps({'Result': False, 'MSG': 'Error'})
            abort(400)
    file = request.files['file']
    print file
    if file.filename == '':
        resp = json.dumps({'Result': False, 'MSG': 'Error, no file!'})
        return Response(resp, status=405, mimetype='application/json')
    if file:
        try:
            filename = secure_filename(file.filename)
            print os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename)
            file.save(os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename))
            resp = json.dumps({'Result': True, 'MSG': 'Upload sukses!', 'VAL': filename})
        except:
            resp = json.dumps({'Result': False, 'MSG': 'Upload gagal!', 'VAL': filename})
    return Response(resp, mimetype='application/json')

@app.route('/api/setfrontend/uploadgambar2', methods=['POST'])
def uploadgambar2():
    if request.method == 'POST':
        if 'file' not in request.files:
            resp = json.dumps({'Result': False, 'MSG': 'Error'})
            abort(400)
    file = request.files['file']
    print file
    if file.filename == '':
        resp = json.dumps({'Result': False, 'MSG': 'Error, no file!'})
        return Response(resp, status=405, mimetype='application/json')
    if file:
        try:
            filename = secure_filename(file.filename)
            print os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename)
            file.save(os.path.join(app.config['PALAPA_FOLDER'] + 'image/', filename))
            resp = json.dumps({'Result': True, 'MSG': 'Upload sukses!', 'VAL': filename})
        except:
            resp = json.dumps({'Result': False, 'MSG': 'Upload gagal!', 'VAL': filename})
    return Response(resp, mimetype='application/json')

@app.route('/api/cekprod/<string:identifier>')
def cekprodiden(identifier):
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbprod'])
    result = engine.execute("select * from a_view_fileidentifier where fileidentifier='%s'" % (identifier))   
    for row in result:
        print row
    try:
        if row is not None:
            resp = json.dumps({'Result': True, 'MSG': 'Ada!'})
    except:
        resp = json.dumps({'Result': False, 'MSG': 'Tidak Ada!'})
    return Response(resp, mimetype='application/json')

@app.route('/api/cekpub/<string:identifier>')
def cekpubiden(identifier):
    engine = create_engine(app.config['SQLALCHEMY_BINDS']['dbpub'])
    result = engine.execute("select * from a_view_fileidentifier where fileidentifier='%s'" % (identifier))   
    for row in result:
        print row
    try:
        if row is not None:
            resp = json.dumps({'Result': True, 'MSG': 'Ada!'})
    except:
        resp = json.dumps({'Result': False, 'MSG': 'Tidak Ada!'})
    return Response(resp, mimetype='application/json')

    # APP MAIN RUNTIME

if __name__ == '__main__':
    if not os.path.exists('gs_db.sqlite'):
        db.create_all()
    app.run(debug=True,host='0.0.0.0', port=5001, threaded=True, passthrough_errors=False)

