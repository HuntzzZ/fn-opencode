#!/usr/bin/env python3
"""飞牛 fnOS 子路径反向代理网关。

为什么需要它：
opencode 的 Web UI 只能整站运行在根路径（`/`），而飞牛在网关模式下会把应用挂到
`/app/<appname>/` 这样的子路径后面。本网关监听一个 Unix socket，把飞牛网关转来的
请求转发给本地 opencode 端口，并做三件事：

1. 剥掉入站请求的网关前缀；
2. 把 opencode 返回的 HTML 注入 `<base>` 与一段桥接脚本，让 SPA 里的
   fetch / XHR / WebSocket / EventSource / history / 资源链接都带上前缀；
3. 回写 Location 与 Set-Cookie 的 Path。

反向代理与子路径改写是通用做法，这里按 opencode 的实际需要精简实现。
"""

import argparse
import atexit
import gzip
import http.client
import logging
import os
import re
import select
import signal
import socket
import sys
from http.server import BaseHTTPRequestHandler

try:
    import socketserver
except ImportError:  # pragma: no cover
    socketserver = None

CHUNK_SIZE = 64 * 1024
HTML_ATTR_RE = re.compile(r'(?i)\b(src|href|action|poster)\s*=\s*(["\'])(/[^"\']*)')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("fngateway")

BRIDGE_JS = r"""
<script>
(function () {
  var PREFIX = "__PREFIX__";
  if (!PREFIX) return;

  function prefixed(p) {
    if (!p || typeof p !== "string") return p;
    if (/^(https?:|blob:|data:|javascript:|about:|#|wss?:)/i.test(p)) {
      try {
        var u = new URL(p, location.href);
        if (u.origin !== location.origin) return p;
      } catch (e) { return p; }
    }
    if (p === PREFIX || p.indexOf(PREFIX + "/") === 0) return p;
    if (p.charAt(0) !== "/" || p.indexOf("//") === 0) return p;
    return PREFIX + p;
  }

  function mapUrl(u) {
    if (!u || typeof u !== "string") return u;
    if (/^(blob:|data:|javascript:|about:|#)/i.test(u)) return u;
    try {
      var url = new URL(u, location.href);
      if (url.origin !== location.origin) return u;
      if (url.pathname === PREFIX || url.pathname.indexOf(PREFIX + "/") === 0) return u;
      url.pathname = PREFIX + (url.pathname.charAt(0) === "/" ? url.pathname : "/" + url.pathname);
      return (u.charAt(0) === "/") ? url.pathname + url.search + url.hash : url.toString();
    } catch (e) { return u; }
  }

  // 把浏览器给的 Authorization 换成 fnOS 网关不会动的手写头，服务端再还原
  function shiftAuth(headers) {
    if (!headers) return;
    try {
      if (typeof Headers !== "undefined" && headers instanceof Headers) {
        if (headers.has("Authorization")) {
          headers.set("X-FnProxy-Authorization", headers.get("Authorization"));
          headers.delete("Authorization");
        }
        return;
      }
      if (Array.isArray(headers)) {
        headers.forEach(function (h) {
          if (h && String(h[0]).toLowerCase() === "authorization") h[0] = "X-FnProxy-Authorization";
        });
        return;
      }
      Object.keys(headers).forEach(function (k) {
        if (k.toLowerCase() === "authorization") {
          headers["X-FnProxy-Authorization"] = headers[k];
          delete headers[k];
        }
      });
    } catch (e) { }
  }

  if (window.fetch) {
    var nativeFetch = window.fetch;
    window.fetch = function (input, init) {
      init = init || {};
      shiftAuth(init.headers);
      if (typeof Request !== "undefined" && input instanceof Request) {
        var mapped = mapUrl(input.url);
        if (mapped !== input.url || (input.headers && input.headers.has && input.headers.has("Authorization"))) {
          try {
            var h = new Headers(input.headers);
            shiftAuth(h);
            input = new Request(mapped, Object.assign({}, init, { headers: h }));
          } catch (e) { }
        }
      } else {
        input = mapUrl(input);
      }
      return nativeFetch.call(this, input, init);
    };
  }

  if (window.XMLHttpRequest) {
    var open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (m, u) {
      arguments[1] = mapUrl(u);
      return open.apply(this, arguments);
    };
    var setHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      if (k && String(k).toLowerCase() === "authorization") k = "X-FnProxy-Authorization";
      return setHeader.call(this, k, v);
    };
  }

  if (window.history) {
    ["pushState", "replaceState"].forEach(function (fn) {
      var orig = history[fn];
      if (!orig) return;
      history[fn] = function (s, t, u) {
        if (u) arguments[2] = mapUrl(u);
        return orig.apply(this, arguments);
      };
    });
  }

  ["Worker", "SharedWorker", "EventSource"].forEach(function (name) {
    var Native = window[name];
    if (!Native) return;
    window[name] = new Proxy(Native, {
      construct: function (target, args, nt) {
        args = [mapUrl(args[0])].concat(args.slice(1));
        return Reflect.construct(target, args, nt);
      }
    });
  });

  if (window.WebSocket) {
    var WS = window.WebSocket;
    window.WebSocket = new Proxy(WS, {
      construct: function (target, args, nt) {
        try {
          var u = new URL(String(args[0]), location.href);
          if (u.pathname !== PREFIX && u.pathname.indexOf(PREFIX + "/") !== 0) {
            u.pathname = PREFIX + (u.pathname.charAt(0) === "/" ? u.pathname : "/" + u.pathname);
            args = [u.toString()].concat(args.slice(1));
          }
        } catch (e) { }
        return Reflect.construct(target, args, nt);
      }
    });
  }

  function hookProp(proto, prop) {
    if (!proto) return;
    var d = Object.getOwnPropertyDescriptor(proto, prop);
    if (!d || !d.set || !d.configurable) return;
    var setter = d.set;
    Object.defineProperty(proto, prop, {
      set: function (v) { return setter.call(this, mapUrl(v)); },
      get: d.get, configurable: true, enumerable: true
    });
  }
  [["HTMLImageElement", "src"], ["HTMLLinkElement", "href"], ["HTMLAnchorElement", "href"],
   ["HTMLScriptElement", "src"], ["HTMLIFrameElement", "src"], ["HTMLMediaElement", "src"],
   ["HTMLSourceElement", "src"]].forEach(function (p) {
    hookProp(window[p[0]] && window[p[0]].prototype, p[1]);
  });

  if (window.Element) {
    var setAttr = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (name, value) {
      var n = String(name).toLowerCase();
      if (n === "src" || n === "href" || n === "action") value = mapUrl(value);
      return setAttr.call(this, name, value);
    };
  }

  if (window.open) {
    var nativeOpen = window.open;
    window.open = function (u) {
      arguments[0] = mapUrl(u);
      return nativeOpen.apply(this, arguments);
    };
  }

  if (location.pathname === PREFIX || location.pathname.indexOf(PREFIX + "/") === 0) {
    // 只处理同源 iframe
    var patchIframe = function (el) {
      try {
        el.addEventListener("load", function () {
          try { if (el.contentWindow && el.contentWindow !== window) inject(el.contentWindow); } catch (e) { }
        });
      } catch (e) { }
    };
    if (window.MutationObserver) {
      new MutationObserver(function (muts) {
        muts.forEach(function (m) {
          Array.prototype.forEach.call(m.addedNodes || [], function (n) {
            if (n && n.tagName === "IFRAME") patchIframe(n);
          });
        });
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
  }

  function inject(win) {
    try {
      if (!win || win.__fnGateway) return;
      win.__fnGateway = true;
      var doc = win.document;
      if (doc) {
        var head = doc.head || doc.documentElement;
        var base = doc.createElement("base");
        base.href = PREFIX + "/";
        head.insertBefore(base, head.firstChild);
      }
    } catch (e) { }
  }

  inject(window);
})();
</script>
"""


def strip_prefix(path, prefix):
    if prefix and (path == prefix or path.startswith(prefix + "/")):
        path = path[len(prefix):]
        return path or "/"
    return path or "/"


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        try:
            logger.info("%s %s", self.command, self.path)
        except Exception:
            pass

    def do_GET(self):
        self.proxy()

    def do_HEAD(self):
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_PUT(self):
        self.proxy()

    def do_PATCH(self):
        self.proxy()

    def do_DELETE(self):
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()

    # ---- 内部工具 -------------------------------------------------
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > 0:
            return self.rfile.read(length)
        return None

    def _forward_headers(self, target_host, target_port):
        headers = {}
        auth = None
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in ("host", "origin", "connection", "sec-fetch-site", "transfer-encoding"):
                continue
            if lk == "x-fnproxy-authorization":
                auth = v
                continue
            if lk == "authorization":
                # 浏览器原始凭据优先，飞牛注入的稍后会被覆盖
                auth = auth or v
                continue
            headers[k] = v
        if auth:
            headers["Authorization"] = auth
        headers["Host"] = "%s:%s" % (target_host, target_port)
        headers["Connection"] = "close"
        return headers

    def proxy(self):
        prefix = self.server.prefix
        host = self.server.target_host
        port = self.server.target_port

        if self.headers.get("Upgrade", "").lower() == "websocket":
            self.tunnel_websocket(prefix, host, port)
            return

        req_path = strip_prefix(self.path, prefix)
        body = self._read_body()
        headers = self._forward_headers(host, port)

        try:
            conn = http.client.HTTPConnection(host, port, timeout=30)
            conn.request(self.command, req_path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as exc:
            logger.error("代理失败 %s %s: %s", self.command, self.path, exc)
            self.send_error(502, "Bad Gateway")
            return

        ctype = (resp.getheader("Content-Type") or "").lower()
        cenc = (resp.getheader("Content-Encoding") or "").lower()
        out = []
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in ("content-length", "transfer-encoding", "connection", "content-encoding",
                      "content-security-policy", "content-security-policy-report-only"):
                continue
            if lk == "location" and v.startswith("/") and not v.startswith("//") \
                    and not v.startswith(prefix + "/"):
                v = prefix + v
            elif lk == "set-cookie":
                v = re.sub(r'(?i)path=/;', "Path=%s/;" % prefix, v)
                if v.lower().endswith("path=/"):
                    v = v[:-7] + "Path=%s/" % prefix
            out.append((k, v))

        if "text/html" in ctype and self.command != "HEAD":
            raw = resp.read()
            if "gzip" in cenc:
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            text = raw.decode("utf-8", errors="ignore")
            text = HTML_ATTR_RE.sub(
                lambda m: m.group(0) if m.group(3).startswith(prefix) else
                "%s=%s%s%s" % (m.group(1), m.group(2), prefix, m.group(3)),
                text)
            inject = '<base href="%s/">' % prefix + self.server.bridge
            m = re.search(r"(?i)<head[^>]*>", text)
            text = (text[:m.end()] + inject + text[m.end():]) if m else (inject + text)
            payload = text.encode("utf-8")
            conn.close()
            self._send_raw(resp.status, resp.reason, out, payload, "text/html; charset=utf-8")
            return

        conn.close()
        self._send_stream(resp.status, resp.reason, out, resp)

    def _send_raw(self, status, reason, headers, payload, ctype):
        self.wfile.write(("HTTP/1.1 %d %s\r\n" % (status, reason)).encode("latin-1"))
        for k, v in headers:
            self.wfile.write(("%s: %s\r\n" % (k, v)).encode("latin-1"))
        self.wfile.write(("Content-Type: %s\r\n" % ctype).encode("latin-1"))
        self.wfile.write(("Content-Length: %d\r\n" % len(payload)).encode("latin-1"))
        self.wfile.write(b"Connection: close\r\n\r\n")
        self.wfile.write(payload)
        self.close_connection = True

    def _send_stream(self, status, reason, headers, resp):
        self.wfile.write(("HTTP/1.1 %d %s\r\n" % (status, reason)).encode("latin-1"))
        for k, v in headers:
            self.wfile.write(("%s: %s\r\n" % (k, v)).encode("latin-1"))
        self.wfile.write(b"Connection: close\r\n\r\n")
        while True:
            try:
                chunk = resp.read(CHUNK_SIZE)
            except Exception:
                break
            if not chunk:
                break
            self.wfile.write(chunk)
        self.close_connection = True

    def tunnel_websocket(self, prefix, host, port):
        req_path = strip_prefix(self.path, prefix)
        target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            target.connect((host, port))
        except Exception as exc:
            logger.error("WebSocket 连接后端失败: %s", exc)
            self.send_error(502, "Bad Gateway")
            return
        handshake = ["%s %s HTTP/1.1" % (self.command, req_path)]
        auth = None
        for k, v in self.headers.items():
            lk = k.lower()
            if lk == "host":
                handshake.append("Host: %s:%s" % (host, port))
            elif lk == "origin":
                handshake.append("Origin: http://%s:%s" % (host, port))
            elif lk == "x-fnproxy-authorization":
                auth = v
            elif lk == "authorization":
                auth = auth or v
            else:
                handshake.append("%s: %s" % (k, v))
        if auth:
            handshake.append("Authorization: %s" % auth)
        handshake.append("\r\n")
        target.sendall("\r\n".join(handshake).encode("utf-8"))

        peers = [self.connection, target]
        try:
            while True:
                readable, _, errored = select.select(peers, [], peers, 60)
                if errored:
                    break
                if not readable:
                    break
                for s in readable:
                    data = s.recv(CHUNK_SIZE)
                    if not data:
                        return
                    (target if s is self.connection else self.connection).sendall(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True
            target.close()


if hasattr(socketserver, "UnixStreamServer"):

    class ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
        request_queue_size = 128

        def __init__(self, socket_path, target_host, target_port, prefix):
            self.target_host = target_host
            self.target_port = target_port
            self.prefix = prefix.rstrip("/")
            self.bridge = BRIDGE_JS.replace("__PREFIX__", self.prefix)
            if os.path.exists(socket_path):
                try:
                    os.unlink(socket_path)
                except OSError:
                    pass
            super().__init__(socket_path, GatewayHandler)
            try:
                os.chmod(socket_path, 0o666)
            except OSError:
                pass

else:  # pragma: no cover - 非 Unix 平台无法提供 Unix socket

    class ThreadingUnixServer(object):  # type: ignore
        def __init__(self, *args, **kwargs):
            raise RuntimeError("当前平台不支持 Unix Domain Socket")


def parse_listen(value):
    value = value.replace("http://", "").replace("https://", "").strip().rstrip("/")
    if ":" in value:
        host, _, port = value.rpartition(":")
        return (host or "127.0.0.1"), int(port)
    return "127.0.0.1", int(value)


def main():
    parser = argparse.ArgumentParser(description="fnOS 子路径反向代理网关")
    parser.add_argument("--listen", required=True, help="后端地址，如 127.0.0.1:14096")
    parser.add_argument("--socket", required=True, help="监听的 Unix socket 路径")
    parser.add_argument("--prefix", required=True, help="网关前缀，如 /app/com.opencode.web")
    args = parser.parse_args()

    host, port = parse_listen(args.listen)

    def cleanup():
        if os.path.exists(args.socket):
            try:
                os.unlink(args.socket)
            except OSError:
                pass

    atexit.register(cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))

    server = ThreadingUnixServer(args.socket, host, port, args.prefix)
    logger.info("网关已启动: socket %s -> %s:%s (前缀 %s)", args.socket, host, port, args.prefix)
    try:
        server.serve_forever()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
