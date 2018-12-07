APP_BASE = "C:/PALAPA/palapa-api/"
SECURITY_TRACKABLE = True
APP_BASE = "C:/PALAPA/palapa-api/"
SECURITY_TRACKABLE = True
SECURITY_PASSWORD_HASH = 'pbkdf2_sha512'
SECURITY_PASSWORD_SALT = 'PALAPA_ini_PALAPA_ini_PALAPA_ini_PALAPA'
WTF_CSRF_ENABLED = False
SECURITY_TOKEN_MAX_AGE = 365 * 24 * 60 * 60 * 1000
SECRET_KEY = 'PALAPA ini PALAPA ini PALAPA ini PALAPA'
SQLALCHEMY_DATABASE_URI = 'postgres://palapa:palapa@103.41.169.65/palapa'
SQLALCHEMY_BINDS = {
    'dbdev': 'postgres://palapa:palapa@103.41.169.65/palapa_dev',
    'dbprod': 'postgres://palapa:palapa@103.41.169.65/palapa_prod',
    'dbpub': 'postgres://palapa:palapa@103.41.169.65/palapa_pub',
    'services': 'postgres://palapa:palapa@103.41.169.65/palapa'
}
SQLALCHEMY_COMMIT_ON_TEARDOWN = True
SQLALCHEMY_TRACK_MODIFICATIONS = True
SQLALCHEMY_DATASTORE = 'postgres://palapa:palapa@103.41.169.65/'
GEOSERVER_REST_URL = 'http://103.41.169.65:8080/geoserver/rest/'
GEOSERVER_WMS_URL = 'http://103.41.169.65:8080/geoserver/wms?'
GEOSERVER_WFS_URL = 'http://103.41.169.65:8080/geoserver/wfs?'
GEOSERVER_WMS_OUT = 'http://103.41.169.65:8080/geoserver/wms?'
GEOSERVER_WFS_OUT = 'http://103.41.169.65:8080/geoserver/wfs?'
GEOSERVER_USER = 'palapa'
GEOSERVER_PASS = 'palapa'
GEOSERVER_THUMBNAILS = 'C:/PALAPA_DATA/DATA/'
GEOSERVER_DATA_DIR= 'C:/Program Files (x86)/Apache Software Foundation/Tomcat 7.0/webapps/geoserver/data/'
GEOSERVER_LAYERS_PROP =	'C:/Program Files (x86)/Apache Software Foundation/Tomcat 7.0/webapps/geoserver/data/security/layers.properties'
GEOSERVER_SERVICES_PROP = 'C:/Program Files (x86)/Apache Software Foundation/Tomcat 7.0/webapps/geoserver/data/security/services.properties'
DATASTORE_HOST = '103.41.169.65'
DATASTORE_PORT = '5432'
DATASTORE_USER = 'palapa'
DATASTORE_PASS = 'palapa'
DATASTORE_DB = 'palapa'
UPLOAD_FOLDER = 'C:/PALAPA_DATA/UPLOADS/'
RASTER_FOLDER = 'C:/PALAPA_DATA/DATA/'
RASTER_STORE = 'C:/PALAPA_DATA/STORE/'
DOCUMENTS_FOLDER = 'C:/PALAPA_DATA/DOCUMENTS/'
DOWNLOADS_FOLDER = 'C:/PALAPA_DATA/DOWNLOADS/'
ALLOWED_EXTENSIONS = set(['zip', 'ZIP'])
ALLOWED_VECTOR = set(['shp', 'SHP'])
ALLOWED_RASTER = set(['tiff', 'tif', 'TIF', 'TIFF'])
CSW_URL = 'http://103.41.169.65/csw'
PALAPA_FOLDER = 'C:/PALAPA/palapa-frontend/'