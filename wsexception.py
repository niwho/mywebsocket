#coding=utf8
from socket import error as socket_error


class WebSocketError(socket_error):
    """
    Base class for all websocket errors.
    """


class ProtocolError(WebSocketError):
    """
    Raised if an error occurs when de/encoding the websocket protocol.
    """


class FrameTooLargeException(ProtocolError):
    """
    Raised if a frame is received that is too large.
    """



"""
define websocket exceptions
"""

class WebSocketException(Exception):
    """
    websocket exeception class.
    """
    pass

class WebSocketProtocolException(WebSocketException):
    """
    If the webscoket protocol is invalid, this exception will be raised.
    """
    pass

class WebSocketPayloadException(WebSocketException):
    """
    If the webscoket payload is invalid, this exception will be raised.
    """
    pass

class WebSocketConnectionClosedException(WebSocketException):
    """
    If remote host closed the connection or some network error happened,
    this exception will be raised.
    """
    pass

class WebSocketTimeoutException(WebSocketException):
    """
    WebSocketTimeoutException will be raised at socket timeout during read/write data.
    """
    pass

class WebSocketProxyException(WebSocketException):
    """
    WebSocketProxyException will be raised when proxy error occured.
    """
    pass


