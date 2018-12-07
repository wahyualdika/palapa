import sys
sys.path.append('c:/PALAPA/palapa-api/')

#from gs_api_ws import app as application
import gs_api_ws

if __name__ == '__main__':
	#app.run()
    app.run(debug=True, port=5001, threaded=True, passthrough_errors=False)