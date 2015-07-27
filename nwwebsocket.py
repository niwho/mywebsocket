# coding=utf8

from gevent import monkey 
monkey.patch_all()

import struct
#import socket
from utf8validator import Utf8Validator
import requests,json
import os
from urlparse import urlparse
import base64,uuid
import ssl
try:
    import ssl
    from ssl import SSLError
    if hasattr(ssl, "match_hostname"):
        from ssl import match_hostname
    else:
        from backports.ssl_match_hostname import match_hostname

    HAVE_SSL = True
except ImportError:
    # dummy class of SSLError for ssl none-support environment.
    class SSLError(Exception):
        pass
    print 'no ssl supported'
    HAVE_SSL = False
import hashlib
from wsexception import *
#from gevent.server import StreamServer

from gevent import *
from gevent.socket import *

from socket import error
from mylogging import create_logger
import traceback
import time

_HEADERS_TO_CHECK = {
    "upgrade": "websocket",
    "connection": "upgrade",
    }
MSG_SOCKET_DEAD = "Socket is dead"
MSG_ALREADY_CLOSED = "Connection is already closed"
MSG_CLOSED = "Connection closed"

class websocket(object):
    
    VERSION=13
    
    OPCODE_CONTINUATION = 0x00
    OPCODE_TEXT = 0x01
    OPCODE_BINARY = 0x02
    OPCODE_CLOSE = 0x08
    OPCODE_PING = 0x09
    OPCODE_PONG = 0x0a
    
    def __init__(self, url):
        self.url = url
        self.sock=None
        fmt = '%(asctime)s - %(filename)s:%(lineno)s - %(name)s - %(message)s'  
        self.logger=create_logger('slacklog',True,fmt)
        pass
    
    def _parse_url(self, url):
        """
        parse url and the result is tuple of
        (hostname, port, resource path and the flag of secure mode)

        url: url string.
        """
        if ":" not in url:
            raise ValueError("url is invalid")
    
        scheme, url = url.split(":", 1)
    
        parsed = urlparse(url, scheme="ws")
        if parsed.hostname:
            hostname = parsed.hostname
        else:
            raise ValueError("hostname is invalid")
        port = 0
        if parsed.port:
            port = parsed.port
    
        is_secure = False
        if scheme == "ws":
            if not port:
                port = 80
        elif scheme == "wss":
            is_secure = True
            if not port:
                port = 443
        else:
            raise ValueError("scheme %s is invalid" % scheme)
    
        if parsed.path:
            resource = parsed.path
        else:
            resource = "/"
    
        if parsed.query:
            resource += "?" + parsed.query

        return (hostname, port, resource, is_secure)
    def _read_headers(self):
        status = None
        headers = {}
        #print 'aaaaaaa'
        #print self.sock.read()
        #print 'bbbbbb'
        #while True:
        #    line = self._recv_line()
        #    line = line.decode('utf-8').strip()
        #    if not line:
        #        break
        print 'ffff'
        #self.sock.read()
        fileobj = self.sock.makefile()
        print 'gggg'
        k=0
        n = 0
        while True:
        #for line in fileobj.readlines():
            line = fileobj.readline()    
            n+=1
            print n,line
            if line=='\r\n':
                break
                #continue
            
            if not status:
                status_info = line.split(" ", 2)
                status = int(status_info[1])
            else:
                kv = line.split(":", 1)
                if len(kv) == 2:
                    key, value = kv
                    headers[key.lower()] = value.strip().lower()
                else:
                    raise WebSocketException("Invalid header")
        return status, headers
    
    def _get_resp_headers(self, success_status = 101):
        status, resp_headers = self._read_headers()
        if status != success_status:
            self.close()
            raise WebSocketException("Handshake status %d" % status)
        return resp_headers

    def _get_handshake_headers(self, resource, host, port, options):
        headers = []
        headers.append("GET %s HTTP/1.1" % resource)
        headers.append("Upgrade: websocket")
        headers.append("Connection: Upgrade")
        if port == 80:
            hostport = host
        else:
            hostport = "%s:%d" % (host, port)
        headers.append("Host: %s" % hostport)

        if "origin" in options:
            headers.append("Origin: %s" % options["origin"])
        else:
            headers.append("Origin: http://%s" % hostport)

        key = base64.encodestring(uuid.uuid4().bytes).decode('utf8').strip()
        headers.append("Sec-WebSocket-Key: %s" % key)
        headers.append("Sec-WebSocket-Version: %s" % self.VERSION)

        subprotocols = options.get("subprotocols")
        if subprotocols:
            headers.append("Sec-WebSocket-Protocol: %s" % ",".join(subprotocols))

        if "header" in options:
            headers.extend(options["header"])

        cookie = options.get("cookie", None)

        if cookie:
            headers.append("Cookie: %s" % cookie)

        headers.append("")
        headers.append("")

        return headers, key
    def _validate_header(self, headers, key, subprotocols):
        for k, v in _HEADERS_TO_CHECK.items():
            r = headers.get(k, None)
            if not r:
                return False
            r = r.lower()
            if v != r:
                return False
        
        if subprotocols:
            subproto = headers.get("sec-websocket-protocol", None)
            if not subproto or subproto not in subprotocols:
            #   logger.error("Invalid subprotocol: " + str(subprotocols))
                return False
            self.subprotocol = subproto


        result = headers.get("sec-websocket-accept", None)
        if not result:
            return False
        result = result.lower()

        #if isinstance(result, six.text_type):
        #    result = result.encode('utf-8')

        value = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode('utf-8')
        hashed = base64.encodestring(hashlib.sha1(value).digest()).strip().lower()
        return hashed == result
    def _handshake(self, host, port, resource, **options):
        headers, key = self._get_handshake_headers(resource, host, port, options)

        header_str = "\r\n".join(headers)
        #self._send(header_str)
        #_dump("request header", header_str)
        self.sock.sendall(header_str)
        
        resp_headers = self._get_resp_headers()
        #base64.b64encode( hashlib.sha1(key + self.GUID).digest()
        success = self._validate_header(resp_headers, key, options.get("subprotocols"))
        if not success:
            self.close()
            raise WebSocketException("Invalid WebSocket Header")

        self.connected = True
        self.closed = False
        self.logger.debug('handshake ok')
        #print 'handshake ok'
    def connect(self):
        hostname, port, resource, is_secure = self._parse_url(self.url)
        addrinfo_list = getaddrinfo(hostname, port, 0, 0, SOL_TCP)
        try:
            self.sock = socket(addrinfo_list[0][0])
            self.sock.connect(addrinfo_list[0][4])
            if is_secure:
                if HAVE_SSL:
                    sslopt = dict(cert_reqs=ssl.CERT_REQUIRED)
                    certPath = os.path.join(
                        os.path.dirname(__file__), "cacert.pem")
                    if os.path.isfile(certPath):
                        sslopt['ca_certs'] = certPath
                    #sslopt.update(self.sslopt)
                    check_hostname = sslopt.pop('check_hostname', True)
                    self.sock = ssl.wrap_socket(self.sock, **sslopt)
                    if (sslopt["cert_reqs"] != ssl.CERT_NONE
                            and check_hostname):
                        match_hostname(self.sock.getpeercert(), hostname)
                else:
                    raise WebSocketException("SSL not available.")
            self.stream=Stream(self)
        except Exception, e:
            raise e
        self._handshake(hostname, port, resource)
        

        self.raw_write = self.stream.write
        self.raw_read = self.stream.read

        self.utf8validator = Utf8Validator()
        #self.handler = handler

    def __del__(self):
        try:
            #self.close()
            pass
        except:
            # close() may fail if __init__ didn't complete
            pass

    def _decode_bytes(self, bytestring):
        """
        Internal method used to convert the utf-8 encoded bytestring into
        unicode.

        If the conversion fails, the socket will be closed.
        """

        if not bytestring:
            return u''

        try:
            return bytestring.decode('utf-8')
        except UnicodeDecodeError:
            self.close(1007)

            raise

    def _encode_bytes(self, text):
        """
        :returns: The utf-8 byte string equivalent of `text`.
        """

        if isinstance(text, str):
            return text

        if not isinstance(text, unicode):
            text = unicode(text or '')

        return text.encode('utf-8')

    def _is_valid_close_code(self, code):
        """
        :returns: Whether the returned close code is a valid hybi return code.
        """
        if code < 1000:
            return False

        if 1004 <= code <= 1006:
            return False

        if 1012 <= code <= 1016:
            return False

        if code == 1100:
            # not sure about this one but the autobahn fuzzer requires it.
            return False

        if 2000 <= code <= 2999:
            return False

        return True
    
    def handle_close(self, header, payload):
        """
        Called when a close frame has been decoded from the stream.

        :param header: The decoded `Header`.
        :param payload: The bytestring payload associated with the close frame.
        """
        if not payload:
            self.close(1000, None)

            return

        if len(payload) < 2:
            raise ProtocolError('Invalid close frame: {0} {1}'.format(
                header, payload))

        code = struct.unpack('!H', str(payload[:2]))[0]
        payload = payload[2:]

        if payload:
            validator = Utf8Validator()
            val = validator.validate(payload)

            if not val[0]:
                raise UnicodeError

        if not self._is_valid_close_code(code):
            raise ProtocolError('Invalid close code {0}'.format(code))

        self.close(code, payload)

    def handle_ping(self, header, payload):
        #服务端会收到这个消息
        self.send_frame(payload, self.OPCODE_PONG)
        self.logger.debug('ping:'+payload)
    def handle_pong(self, header, payload):
        #客户端会收到这个消息
        self.send_frame(payload, self.OPCODE_PONG)
        self.logger.debug('pong:'+payload)
        pass
    def handle_message(self,tp,message):
        self.logger.debug('message:'+message)
        
    def read_frame(self):
        """
        Block until a full frame has been read from the socket.

        This is an internal method as calling this will not cleanup correctly
        if an exception is called. Use `receive` instead.

        :return: The header and payload as a tuple.
        """

        header = Header.decode_header(self.stream)

        if header.flags:
            raise ProtocolError

        if not header.length:
            return header, ''

        try:
            payload = self.raw_read(header.length)
        except error:
            payload = ''
        except Exception:
            # TODO log out this exception
            payload = ''

        if len(payload) != header.length:
            raise WebSocketError('Unexpected EOF reading frame payload')

        if header.mask:
            payload = header.unmask_payload(payload)

        return header, payload

    def validate_utf8(self, payload):
        # Make sure the frames are decodable independently
        self.utf8validate_last = self.utf8validator.validate(payload)

        if not self.utf8validate_last[0]:
            raise UnicodeError("Encountered invalid UTF-8 while processing "
                               "text message at payload octet index "
                               "{0:d}".format(self.utf8validate_last[3]))

    def read_message(self):
        """
        Return the next text or binary message from the socket.

        This is an internal method as calling this will not cleanup correctly
        if an exception is called. Use `receive` instead.
        """
        opcode = None
        message = ""

        while True:
            header, payload = self.read_frame()
            f_opcode = header.opcode

            if f_opcode in (self.OPCODE_TEXT, self.OPCODE_BINARY):
                # a new frame
                if opcode:
                    raise ProtocolError("The opcode in non-fin frame is "
                                        "expected to be zero, got "
                                        "{0!r}".format(f_opcode))

                # Start reading a new message, reset the validator
                self.utf8validator.reset()
                self.utf8validate_last = (True, True, 0, 0)

                opcode = f_opcode

            elif f_opcode == self.OPCODE_CONTINUATION:
                if not opcode:
                    raise ProtocolError("Unexpected frame with opcode=0")

            elif f_opcode == self.OPCODE_PING:
                self.handle_ping(header, payload)
                continue

            elif f_opcode == self.OPCODE_PONG:
                self.handle_pong(header, payload)
                continue

            elif f_opcode == self.OPCODE_CLOSE:
                self.handle_close(header, payload)
                return

            else:
                raise ProtocolError("Unexpected opcode={0!r}".format(f_opcode))

            if opcode == self.OPCODE_TEXT:
                self.validate_utf8(payload)

            message += payload

            if header.fin:
                break

        if opcode == self.OPCODE_TEXT:
            self.validate_utf8(message)
            #return message
            self.handle_message(opcode,message)
        else:
            #return bytearray(message)
            self.handle_message(opcode,bytearray(message))

    def receive(self):
        """
        Read and return a message from the stream. If `None` is returned, then
        the socket is considered closed/errored.
        """

        if self.closed:
            #self.current_app.on_close(MSG_ALREADY_CLOSED)
            raise WebSocketError(MSG_ALREADY_CLOSED)

        try:
            return self.read_message()
        except UnicodeError,e:
            print traceback.format_exc()
            self.close(1007)
        except ProtocolError,e:
            print traceback.format_exc()
            self.close(1002)
        except error,e:
            #print traceback.format_exc()
            self.close()
            #self.current_app.on_close(MSG_CLOSED)

        return None

    def send_frame(self, message, opcode):
        """
        Send a frame over the websocket with message as its payload
        """
        if self.closed:
            #self.current_app.on_close(MSG_ALREADY_CLOSED)
            raise WebSocketError(MSG_ALREADY_CLOSED)

        mask_key = ''
        if opcode == self.OPCODE_TEXT :#or opcode == self.OPCODE_PING:
            mask_key = os.urandom(4)
            message = self._encode_bytes(message)
            message = Header.mask_payload_s(message,mask_key)
        elif opcode == self.OPCODE_BINARY:
            message = str(message)
        
        header = Header.encode_header(True, opcode, mask_key, len(message), 0)
        try:
            self.raw_write(header + message)
        except error:
            raise WebSocketError(MSG_SOCKET_DEAD)
    
    #send_frame 参数简化版
    def send(self, message, binary=None):
        """
        Send a frame over the websocket with message as its payload
        """
        if binary is None:
            binary = not isinstance(message, (str, unicode))

        opcode = self.OPCODE_BINARY if binary else self.OPCODE_TEXT

        try:
            self.send_frame(message, opcode)
        except WebSocketError:
            #self.current_app.on_close(MSG_SOCKET_DEAD)
            raise WebSocketError(MSG_SOCKET_DEAD)

    def close(self, code=1000, message=''):
        """
        Close the websocket and connection, sending the specified code and
        message.  The underlying socket object is _not_ closed, that is the
        responsibility of the initiator.
        """

        if self.closed:
            #self.current_app.on_close(MSG_ALREADY_CLOSED)
            pass

        try:
            message = self._encode_bytes(message)

            self.send_frame(
                struct.pack('!H%ds' % len(message), code, message),
                opcode=self.OPCODE_CLOSE)
        except WebSocketError:
            # Failed to write the closing frame but it's ok because we're
            # closing the socket anyway.
            self.logger.debug("Failed to write closing frame -> closing socket")
        finally:
            self.logger.debug("Closed WebSocket")
            print traceback.format_exc()
            self.closed = True

            self.stream = None
            self.raw_write = None
            self.raw_read = None

            self.environ = None

            #self.current_app.on_close(MSG_ALREADY_CLOSED)
    def idle_ping(self):
        k=1000
        while True:
            msg = '{ "id": %d, "type": "ping",  "time": "%f"  }'%(k,time.time(),)
            self.send(msg)
            k+=1
            #self.send_frame('aaa', self.OPCODE_PING)
            self.logger.debug('myping:'+msg)
            sleep(5)
    
    def run_forever(self):
        spawn(self.idle_ping)
        #self.send('{"type": "message", "channel": "C024BE91L", "text": "Hello world"}')
        while True:
            self.receive()
            #self.send('{"type": "message", "channel": "C024BE91L", "text": "Hello world"}')
            print '++++++++++++++++++++++'
            if self.closed:
                break
            
class Stream(object):
    """
    Wraps the handler's socket/rfile attributes and makes it in to a file like
    object that can be read from/written to by the lower level websocket api.
    """

    __slots__ = ('handler', 'read', 'write')

    def __init__(self, ws):
        #self.handler = handler
        #self.read = handler.rfile.read
        #self.write = handler.socket.sendall
    
        self.handler = None#handler
        self.read = ws.sock.makefile().read
        self.write = ws.sock.sendall
    
    

class Header(object):
    __slots__ = ('fin', 'mask', 'opcode', 'flags', 'length')

    FIN_MASK = 0x80
    OPCODE_MASK = 0x0f
    MASK_MASK = 0x80
    LENGTH_MASK = 0x7f

    RSV0_MASK = 0x40
    RSV1_MASK = 0x20
    RSV2_MASK = 0x10

    # bitwise mask that will determine the reserved bits for a frame header
    HEADER_FLAG_MASK = RSV0_MASK | RSV1_MASK | RSV2_MASK

    def __init__(self, fin=0, opcode=0, flags=0, length=0):
        self.mask = ''
        self.fin = fin
        self.opcode = opcode
        self.flags = flags
        self.length = length

    @classmethod
    def mask_payload_s(cls,payload,mask):
        payload = bytearray(payload)
        mask = bytearray(mask)

        for i in xrange(len(payload)):
            payload[i] ^= mask[i % 4]

        return str(payload)
    
    def mask_payload(self, payload):
        payload = bytearray(payload)
        mask = bytearray(self.mask)

        for i in xrange(self.length):
            payload[i] ^= mask[i % 4]

        return str(payload)

    # it's the same operation
    unmask_payload = mask_payload

    def __repr__(self):
        return ("<Header fin={0} opcode={1} length={2} flags={3} at "
                "0x{4:x}>").format(self.fin, self.opcode, self.length,
                                   self.flags, id(self))

    @classmethod
    def decode_header(cls, stream):
        """
        Decode a WebSocket header.

        :param stream: A file like object that can be 'read' from.
        :returns: A `Header` instance.
        """
        read = stream.read
        data = read(2)

        if len(data) != 2:
            print 'data:',data
            raise WebSocketError("Unexpected EOF while decoding header")

        first_byte, second_byte = struct.unpack('!BB', data)

        header = cls(
            fin=first_byte & cls.FIN_MASK == cls.FIN_MASK,
            opcode=first_byte & cls.OPCODE_MASK,
            flags=first_byte & cls.HEADER_FLAG_MASK,
            length=second_byte & cls.LENGTH_MASK)

        has_mask = second_byte & cls.MASK_MASK == cls.MASK_MASK

        if header.opcode > 0x07:
            if not header.fin:
                raise ProtocolError(
                    "Received fragmented control frame: {0!r}".format(data))

            # Control frames MUST have a payload length of 125 bytes or less
            if header.length > 125:
                raise FrameTooLargeException(
                    "Control frame cannot be larger than 125 bytes: "
                    "{0!r}".format(data))

        if header.length == 126:
            # 16 bit length
            data = read(2)

            if len(data) != 2:
                raise WebSocketError('Unexpected EOF while decoding header')

            header.length = struct.unpack('!H', data)[0]
        elif header.length == 127:
            # 64 bit length
            data = read(8)

            if len(data) != 8:
                raise WebSocketError('Unexpected EOF while decoding header')

            header.length = struct.unpack('!Q', data)[0]

        if has_mask:
            mask = read(4)

            if len(mask) != 4:
                raise WebSocketError('Unexpected EOF while decoding header')

            header.mask = mask

        return header

    @classmethod
    def encode_header(cls, fin, opcode, mask, length, flags):
        """
        Encodes a WebSocket header.

        :param fin: Whether this is the final frame for this opcode.
        :param opcode: The opcode of the payload, see `OPCODE_*`
        :param mask: Whether the payload is masked.
        :param length: The length of the frame.
        :param flags: The RSV* flags.
        :return: A bytestring encoded header.
        """
        first_byte = opcode
        second_byte = 0
        extra = ''

        if fin:
            first_byte |= cls.FIN_MASK

        if flags & cls.RSV0_MASK:
            first_byte |= cls.RSV0_MASK

        if flags & cls.RSV1_MASK:
            first_byte |= cls.RSV1_MASK

        if flags & cls.RSV2_MASK:
            first_byte |= cls.RSV2_MASK

        # now deal with length complexities
        if length < 126:
            second_byte += length
        elif length <= 0xffff:
            second_byte += 126
            extra = struct.pack('!H', length)
        elif length <= 0xffffffffffffffff:
            second_byte += 127
            extra = struct.pack('!Q', length)
        else:
            raise FrameTooLargeException

        if mask:
            second_byte |= cls.MASK_MASK

            extra += mask

        return chr(first_byte) + chr(second_byte) + extra

if __name__=="__main__":
    params={'token':'xoxp-4181921091-4181921111-4205173537-838ea9'}
    r=requests.get('https://slack.com/api/rtm.start',params=params)
    print r.content
    json.loads(r.content)['url']
    #wwss = websocket('wss://ms152.slack-msgs.com/websocket/B3e6g7NmsMe1lFDWrzFDpAkxo7_NHhQTNbGYWQ5TmGB_NwEg54Ju1Ud2fnKxD83gfneYwGbY/dUQEl9Ldf/7DVdrOXxGhXKUfiF8sB2QYuo=')
    wwss = websocket(json.loads(r.content)['url'])
    #wwss = websocket('ws://127.0.0.1:8000/')
    wwss.connect()
    wwss.run_forever()
