# freecad_mcp_addon.py - FreeCAD MCP Addon v0.9.0
#
# 概要:
#   FreeCAD 内で HTTP サーバー（デフォルト: 127.0.0.1:8765）を起動し、
#   MCP サーバー（freecad_mcp_server.js）からのコマンドを受信して
#   FreeCAD の Part API を実行するアドオンスクリプト。
#
# 使い方:
#   FreeCAD のマクロメニュー（マクロ → マクロを実行）から
#   このファイルを選択して実行してください。
#   起動後は Claude Desktop / Claude Code から FreeCAD を操作できます。
#
# 環境変数:
#   FREECAD_MCP_HOST : サーバーホスト (デフォルト: 127.0.0.1)
#   FREECAD_MCP_PORT : サーバーポート (デフォルト: 8765)
import FreeCAD
import FreeCADGui
import Part
import json
import os
import traceback
import math
import unicodedata
import queue
import threading
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

API_HOST = os.environ.get("FREECAD_MCP_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("FREECAD_MCP_PORT", "8765"))

def _is_existing_mcp_server_alive(host, port, timeout_sec=0.5):
    conn = None
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout_sec)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        if resp.status != 200:
            return False
        payload = json.loads(resp.read().decode("utf-8"))
        return isinstance(payload, dict) and payload.get("status") == "ok"
    except Exception:
        return False
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

class FreeCADMCPAddon:
    def __init__(self):
        self._request_queue = queue.Queue()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._request_id = 0

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._process_queue)
        self.timer.start(20)

        self._http_server = None
        self._http_thread = None
        self._start_http_server()
        FreeCAD.Console.PrintMessage(f"[MCP] FreeCAD MCP Addon started. API endpoint: http://{API_HOST}:{API_PORT}/command\\n")

    # ------------------------------------------------------------------ http/api
    def _next_request_id(self):
        with self._pending_lock:
            self._request_id += 1
            return str(self._request_id)

    def _handle_command_sync(self, command, params, timeout_ms):
        request_id = self._next_request_id()
        done = threading.Event()
        with self._pending_lock:
            self._pending[request_id] = {'event': done, 'response': None}
        self._request_queue.put((request_id, command, params))

        timeout_sec = max(float(timeout_ms) / 1000.0, 0.1)
        if not done.wait(timeout_sec):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            return {
                'status': 'error',
                'message': f'FreeCAD command timeout ({int(timeout_ms)}ms)',
                'traceback': '',
            }

        with self._pending_lock:
            state = self._pending.pop(request_id, None)
        if not state or state.get('response') is None:
            return {
                'status': 'error',
                'message': 'Missing command response.',
                'traceback': '',
            }
        return state['response']

    def _create_http_handler(self):
        addon = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, code, payload):
                data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == '/health':
                    self._send_json(200, {'status': 'ok'})
                    return
                self._send_json(404, {'status': 'error', 'message': 'Not found'})

            def do_POST(self):
                if self.path != '/command':
                    self._send_json(404, {'status': 'error', 'message': 'Not found'})
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    raw = self.rfile.read(length) if length > 0 else b''
                    payload = json.loads(raw.decode('utf-8') if raw else '{}')
                    command = payload.get('command')
                    params = payload.get('parameters') or {}
                    timeout_ms = int(payload.get('timeout_ms', 60000))
                    if not isinstance(command, str) or not command:
                        self._send_json(400, {'status': 'error', 'message': 'Invalid command'})
                        return
                    response = addon._handle_command_sync(command, params, timeout_ms)
                    self._send_json(200, response)
                except Exception as e:
                    self._send_json(500, {'status': 'error', 'message': str(e), 'traceback': traceback.format_exc()})

            def log_message(self, format, *args):
                return

        return Handler

    def _start_http_server(self):
        class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        self._http_server = ThreadingHTTPServer((API_HOST, API_PORT), self._create_http_handler())
        self._http_server.daemon_threads = True
        self._http_thread = threading.Thread(target=self._http_server.serve_forever, name="FreeCADMCPHTTP", daemon=True)
        self._http_thread.start()

    # ------------------------------------------------------------------ queue
    def _process_queue(self):
        while True:
            try:
                request_id, command, params = self._request_queue.get_nowait()
            except queue.Empty:
                break

            try:
                result = self._dispatch(command, params or {})
                response = {'status': 'success', 'result': result}
            except Exception as e:
                FreeCAD.Console.PrintError(f"[MCP] Error: {e}\\n")
                response = {'status': 'error', 'message': str(e), 'traceback': traceback.format_exc()}

            with self._pending_lock:
                state = self._pending.get(request_id)
                if state:
                    state['response'] = response
                    state['event'].set()

    def stop(self):
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            if self._http_server:
                self._http_server.shutdown()
                self._http_server.server_close()
        except Exception:
            pass

    # ------------------------------------------------------------------ dispatch
    def _dispatch(self, command, params):
        handlers = {
            'execute_macro':            self._execute_macro,
            'create_box':               self._create_box,
            'create_cube':              self._create_cube,
            'create_cylinder':          self._create_cylinder,
            'create_sphere':            self._create_sphere,
            'create_cone':              self._create_cone,
            'create_torus':             self._create_torus,
            'create_hemisphere':        self._create_hemisphere,
            'create_polygon_prism':     self._create_polygon_prism,
            'combine_by_name':          self._combine_by_name,
            'move_by_name':             self._move_by_name,
            'rotate_by_name':           self._rotate_by_name,
            'add_fillet':               self._add_fillet,
            'add_chamfer':              self._add_chamfer,
            'hide_body':                self._hide_body,
            'show_body':                self._show_body,
            'copy_body_symmetric':      self._copy_body_symmetric,
            'create_circular_pattern':  self._create_circular_pattern,
            'create_rectangular_pattern': self._create_rectangular_pattern,
            'get_all_bodies':           self._get_all_bodies,
            'get_bounding_box':         self._get_bounding_box,
            'get_body_dimensions':      self._get_body_dimensions,
            'get_faces_info':           self._get_faces_info,
            'get_edges_info':           self._get_edges_info,
            'export_file':              self._export_file,
            'delete_all_features':      self._delete_all_features,
            'save_document':            self._save_document,
            # === 鬯ｮ・ｫ繝ｻ・ｴ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｰ鬯ｯ・ｮ繝ｻ・ｫ髯ｷ閧ｴ・ｺ・ｯ郢ｩ・･驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｿ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｽ鬯ｮ・ｯ繝ｻ・ｷ髣費ｽｨ陞滂ｽｲ繝ｻ・ｽ繝ｻ・｣郢晢ｽｻ繝ｻ・ｰ鬯ｩ蟷｢・ｽ・｢髫ｴ謫ｾ・ｽ・ｴ驛｢譎｢・ｽ・ｻ鬩幢ｽ｢隴趣ｽ｢繝ｻ・ｽ繝ｻ・ｻ鬯ｩ蟷｢・ｽ・｢髫ｴ雜｣・ｽ・｢郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｫ ===
            'create_half_torus':            self._create_half_torus,
            'shell_body':                   self._shell_body,
            'get_body_center':              self._get_body_center,
            'get_mass_properties':          self._get_mass_properties,
            'measure_distance':             self._measure_distance,
            'measure_angle':                self._measure_angle,
            'combine_selection':            self._combine_selection,
            'combine_selection_all':        self._combine_selection_all,
            'check_interference':           self._check_interference,
            'get_body_relationships':       self._get_body_relationships,
            'create_sketch':                self._create_sketch,
            'draw_line_in_sketch':          self._draw_line_in_sketch,
            'draw_circle_in_sketch':        self._draw_circle_in_sketch,
            'draw_rectangle_in_sketch':     self._draw_rectangle_in_sketch,
            'add_coincident_constraint':    self._add_coincident_constraint,
            'add_horizontal_constraint':    self._add_horizontal_constraint,
            'add_vertical_constraint':      self._add_vertical_constraint,
            'add_parallel_constraint':      self._add_parallel_constraint,
            'add_perpendicular_constraint': self._add_perpendicular_constraint,
            'add_tangent_constraint':       self._add_tangent_constraint,
            'add_linear_dimension':         self._add_linear_dimension,
            'add_radius_dimension':         self._add_radius_dimension,
            'extrude_sketch':               self._extrude_sketch,
            'revolve_sketch':               self._revolve_sketch,
            'sweep_sketch':                 self._sweep_sketch,
            'loft_sketches':                self._loft_sketches,
            'create_pipe':                  self._create_pipe,
            'create_section_view':          self._create_section_view,
            'undo':                         self._undo,
            'redo':                         self._redo,
        }
        if command not in handlers:
            raise ValueError(f"Unknown command: {command}")

        # 読み取り系・undo/redo はトランザクション不要
        no_transaction = {
            'get_all_bodies', 'get_bounding_box', 'get_body_dimensions',
            'get_faces_info', 'get_edges_info', 'get_body_center',
            'get_mass_properties', 'measure_distance', 'measure_angle',
            'check_interference', 'get_body_relationships',
            'export_file', 'save_document', 'undo', 'redo', 'execute_macro',
        }
        if command in no_transaction:
            return handlers[command](params)

        doc = self._doc()
        doc.openTransaction(command)
        try:
            result = handlers[command](params)
            doc.commitTransaction()
            return result
        except Exception:
            doc.abortTransaction()
            raise

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_list(value, item_type=None):
        """文字列またはリストを受け取り、リストを返す。item_type が指定された場合は各要素を変換。"""
        if isinstance(value, str):
            value = json.loads(value)
        if item_type is not None:
            value = [item_type(v) for v in value]
        return value

    def _doc(self):
        doc = FreeCAD.activeDocument()
        if doc is None:
            doc = FreeCAD.newDocument("FreeCAD_MCP")
        return doc

    def _fit_view(self):
        try:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass

    def _find(self, doc, name):
        obj = doc.getObject(name)
        if obj:
            return obj
        for o in doc.Objects:
            if o.Label == name:
                return o
        raise ValueError(f"Body '{name}' was not found.")

    def _placement_offset(self, params, w=0, d=0, h=0):
        """鬯ｯ・ｯ繝ｻ・ｩ髮九・・ｽ・ｷ鬮ｫ・ｱ繝ｻ・ｿ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｽ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｮ鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｪ鬯ｩ蟷｢・ｽ・｢髫ｴ蠑ｱ繝ｻ繝ｻ・ｽ繝ｻ・ｼ髫ｴ竏ｫ・ｵ・ｶ髣懶ｽｽ鬯ｩ蟷｢・ｽ・｢髫ｴ謫ｾ・ｽ・ｴ驛｢譎｢・ｽ・ｻ鬩幢ｽ｢隴趣ｽ｢繝ｻ・ｽ繝ｻ・ｨ鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ鬮ｯ讖ｸ・ｽ・ｳ髯樊ｻゑｽｽ・ｲ郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｨ鬯ｮ・｢繝ｻ・ｧ郢晢ｽｻ繝ｻ・ｲ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｮ鬮ｯ・ｷ闔ｨ螟ｲ・ｽ・ｽ繝ｻ・ｱ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｰ鬯ｩ謳ｾ・ｽ・ｵ郢晢ｽｻ繝ｻ・ｺ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｦ FreeCAD.Vector 鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ鬮ｯ讖ｸ・ｽ・ｳ髯樊ｻゑｽｽ・ｲ郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｿ鬮ｫ・ｴ遶擾ｽｫ繝ｻ・ｵ繝ｻ・ｶ驛｢譎｢・ｽ・ｻ"""
        cx = float(params.get('cx', 0))
        cy = float(params.get('cy', 0))
        cz = float(params.get('cz', 0))
        w  = float(w)
        d  = float(d)
        h  = float(h)
        xp = params.get('x_placement', 'center')
        yp = params.get('y_placement', 'center')
        zp = params.get('z_placement', 'center')

        ox = cx - w/2 if xp == 'center' else cx if xp == 'left'   else cx - w
        oy = cy - d/2 if yp == 'center' else cy if yp == 'front'  else cy - d
        oz = cz - h/2 if zp == 'center' else cz if zp == 'bottom' else cz - h
        return FreeCAD.Vector(ox, oy, oz)

    def _recompute_and_fit(self, doc):
        doc.recompute()
        self._fit_view()

    # ------------------------------------------------------------------ shapes
    def _create_box(self, params):
        doc  = self._doc()
        w    = float(params.get('width',  50))
        d    = float(params.get('depth',  30))
        h    = float(params.get('height', 20))
        name = params.get('body_name', 'Box')
        pos  = self._placement_offset(params, w, d, h)

        obj = doc.addObject("Part::Box", name)
        obj.Label  = name
        obj.Length = w
        obj.Width  = d
        obj.Height = h
        obj.Placement = FreeCAD.Placement(pos, FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "width": w, "depth": d, "height": h}

    def _create_cube(self, params):
        s = float(params.get('size', 50))
        p = dict(params)
        p['width'] = p['depth'] = p['height'] = s
        p.setdefault('body_name', 'Cube')
        return self._create_box(p)

    def _create_cylinder(self, params):
        doc    = self._doc()
        r      = float(params.get('radius', 25))
        h      = float(params.get('height', 50))
        name   = params.get('body_name', 'Cylinder')
        cx     = float(params.get('cx', 0))
        cy     = float(params.get('cy', 0))
        cz     = float(params.get('cz', 0))
        zp     = params.get('z_placement', 'center')
        oz     = cz - h/2 if zp == 'center' else cz if zp == 'bottom' else cz - h

        obj = doc.addObject("Part::Cylinder", name)
        obj.Label  = name
        obj.Radius = r
        obj.Height = h
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, oz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "radius": r, "height": h}

    def _create_sphere(self, params):
        doc  = self._doc()
        r    = float(params.get('radius', 25))
        name = params.get('body_name', 'Sphere')
        cx   = float(params.get('cx', 0))
        cy   = float(params.get('cy', 0))
        cz   = float(params.get('cz', 0))

        obj = doc.addObject("Part::Sphere", name)
        obj.Label  = name
        obj.Radius = r
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, cz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "radius": r}

    def _create_cone(self, params):
        doc   = self._doc()
        r1    = float(params.get('radius',  25))
        r2    = float(params.get('radius2', 0))
        h     = float(params.get('height', 50))
        name  = params.get('body_name', 'Cone')
        cx    = float(params.get('cx', 0))
        cy    = float(params.get('cy', 0))
        cz    = float(params.get('cz', 0))
        zp    = params.get('z_placement', 'bottom')
        oz    = cz - h/2 if zp == 'center' else cz if zp == 'bottom' else cz - h

        obj = doc.addObject("Part::Cone", name)
        obj.Label   = name
        obj.Radius1 = r1
        obj.Radius2 = r2
        obj.Height  = h
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, oz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "radius": r1, "radius2": r2, "height": h}

    def _create_torus(self, params):
        doc  = self._doc()
        r1   = float(params.get('major_radius', 30))
        r2   = float(params.get('minor_radius', 10))
        name = params.get('body_name', 'Torus')
        cx   = float(params.get('cx', 0))
        cy   = float(params.get('cy', 0))
        cz   = float(params.get('cz', 0))

        obj = doc.addObject("Part::Torus", name)
        obj.Label   = name
        obj.Radius1 = r1
        obj.Radius2 = r2
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, cz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "major_radius": r1, "minor_radius": r2}

    def _create_hemisphere(self, params):
        doc  = self._doc()
        r    = float(params.get('radius', 25))
        name = params.get('body_name', 'Hemisphere')
        cx   = float(params.get('cx', 0))
        cy   = float(params.get('cy', 0))
        cz   = float(params.get('cz', 0))
        ori  = params.get('orientation', 'positive')

        obj = doc.addObject("Part::Sphere", name)
        obj.Label  = name
        obj.Radius = r
        if ori == 'positive':
            obj.Angle1 = 0
            obj.Angle2 = 90
        else:
            obj.Angle1 = -90
            obj.Angle2 = 0
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, cz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "radius": r, "orientation": ori}

    def _create_polygon_prism(self, params):
        doc   = self._doc()
        sides = int(params.get('num_sides', 6))
        r     = float(params.get('radius', 25))
        h     = float(params.get('height', 50))
        name  = params.get('body_name', 'Prism')
        cx    = float(params.get('cx', 0))
        cy    = float(params.get('cy', 0))
        cz    = float(params.get('cz', 0))
        zp    = params.get('z_placement', 'bottom')
        oz    = cz - h/2 if zp == 'center' else cz if zp == 'bottom' else cz - h

        obj = doc.addObject("Part::Prism", name)
        obj.Label        = name
        obj.Polygon      = sides
        obj.Circumradius = r
        obj.Height       = h
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, oz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "num_sides": sides, "radius": r, "height": h}

    # ------------------------------------------------------------------ boolean
    def _normalize_boolean_operation(self, operation):
        op_map = {
            'join': "Part::Fuse",
            'cut': "Part::Cut",
            'intersect': "Part::Common",
        }
        alias_to_canonical = {
            'union': 'join',
            'fuse': 'join',
            'subtract': 'cut',
            'difference': 'cut',
            'minus': 'cut',
            'sub': 'cut',
            'common': 'intersect',
            'intersection': 'intersect',
            'and': 'intersect',
        }

        # Normalize common variants (full-width chars, separators, casing)
        op = unicodedata.normalize('NFKC', str(operation))
        op = op.strip().lower().replace('-', '').replace('_', '').replace(' ', '')
        canonical = op if op in op_map else alias_to_canonical.get(op)
        if canonical is None:
            supported = "join, cut, intersect"
            aliases = "union/fuse -> join, subtract/difference/minus -> cut, common/intersection -> intersect"
            raise ValueError(f"Unknown operation: {operation}. Supported: {supported}. Aliases: {aliases}")

        return canonical, op_map[canonical]

    def _combine_by_name(self, params):
        doc     = self._doc()
        t_name  = params['target_body']
        to_name = params['tool_body']
        op_raw  = params['operation']
        op, fc_op = self._normalize_boolean_operation(op_raw)
        new_name = params.get('new_body_name', f'{op}_result')

        target = self._find(doc, t_name)
        tool   = self._find(doc, to_name)

        result = doc.addObject(fc_op, new_name)
        result.Label = new_name
        result.Base  = target
        result.Tool  = tool
        target.Visibility = False
        tool.Visibility   = False
        self._recompute_and_fit(doc)
        return {"body_name": result.Label, "operation": op}

    # ------------------------------------------------------------------ transform
    def _move_by_name(self, params):
        doc  = self._doc()
        obj  = self._find(doc, params['body_name'])
        dx   = float(params.get('x_dist', 0))
        dy   = float(params.get('y_dist', 0))
        dz   = float(params.get('z_dist', 0))
        pl   = obj.Placement
        pl.move(FreeCAD.Vector(dx, dy, dz))
        obj.Placement = pl
        doc.recompute()
        return {"body_name": obj.Label, "moved": [dx, dy, dz]}

    def _rotate_by_name(self, params):
        doc   = self._doc()
        obj   = self._find(doc, params['body_name'])
        aname = params.get('axis', 'z')
        angle = float(params.get('angle', 90))
        cx    = float(params.get('cx', 0))
        cy    = float(params.get('cy', 0))
        cz    = float(params.get('cz', 0))
        axes  = {'x': FreeCAD.Vector(1,0,0), 'y': FreeCAD.Vector(0,1,0), 'z': FreeCAD.Vector(0,0,1)}
        rot   = FreeCAD.Rotation(axes[aname], angle)
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, cz), rot) * obj.Placement
        doc.recompute()
        return {"body_name": obj.Label, "axis": aname, "angle": angle}

    # ------------------------------------------------------------------ edge ops
    def _add_fillet(self, params):
        doc      = self._doc()
        name     = params['body_name']
        radius   = float(params.get('radius', 1))
        indices  = self._parse_list(params.get('edge_indices', []), int)
        obj      = self._find(doc, name)

        edge_count = len(obj.Shape.Edges)
        targets    = indices if indices else list(range(edge_count))

        current_radius = radius
        min_radius     = 0.01
        shrink_factor  = 0.5
        max_attempts   = 6

        for attempt in range(max_attempts):
            fillet       = doc.addObject("Part::Fillet", f"{name}_Fillet")
            fillet.Base  = obj
            fillet.Edges = [(i + 1, current_radius, current_radius) for i in targets]
            obj.Visibility = False
            doc.recompute()

            # 形状が有効かチェック（BoundBox の有限値確認）
            shape = fillet.Shape
            try:
                import math
                bb = shape.BoundBox
                bb_ok = (
                    shape is not None and not shape.isNull()
                    and math.isfinite(bb.XMin) and math.isfinite(bb.XMax)
                    and math.isfinite(bb.YMin) and math.isfinite(bb.YMax)
                    and math.isfinite(bb.ZMin) and math.isfinite(bb.ZMax)
                )
            except Exception:
                bb_ok = False
            if bb_ok:
                self._fit_view()
                return {
                    "body_name": fillet.Label,
                    "radius": current_radius,
                    "edges_applied": len(targets),
                    "requested_radius": radius if current_radius != radius else None,
                }

            # 無効な場合はフィレットを削除してベースを復元し、半径を縮小して再試行
            doc.removeObject(fillet.Name)
            obj.Visibility = True
            doc.recompute()

            next_radius = current_radius * shrink_factor
            if next_radius < min_radius:
                raise RuntimeError(
                    f"フィレット失敗: 半径 {radius} から {current_radius} まで試しましたが形状が無効です。"
                    f" エッジに対してフィレット半径が大きすぎる可能性があります。"
                )
            current_radius = next_radius

        raise RuntimeError(
            f"フィレット失敗: {max_attempts} 回試行しましたが有効な形状を生成できませんでした。"
        )

    def _add_chamfer(self, params):
        doc      = self._doc()
        name     = params['body_name']
        dist     = float(params.get('distance', 1))
        indices  = self._parse_list(params.get('edge_indices', []), int)
        obj      = self._find(doc, name)

        chamfer        = doc.addObject("Part::Chamfer", f"{name}_Chamfer")
        chamfer.Base   = obj
        edge_count     = len(obj.Shape.Edges)
        targets        = indices if indices else list(range(edge_count))
        chamfer.Edges  = [(i + 1, dist, dist) for i in targets]
        obj.Visibility = False
        self._recompute_and_fit(doc)
        return {"body_name": chamfer.Label, "distance": dist, "edges_applied": len(targets)}

    # ------------------------------------------------------------------ visibility
    def _hide_body(self, params):
        obj = self._find(self._doc(), params['body_name'])
        obj.Visibility = False
        return {"body_name": obj.Label, "visible": False}

    def _show_body(self, params):
        obj = self._find(self._doc(), params['body_name'])
        obj.Visibility = True
        return {"body_name": obj.Label, "visible": True}

    # ------------------------------------------------------------------ patterns
    def _copy_body_symmetric(self, params):
        doc      = self._doc()
        src_name = params['source_body_name']
        new_name = params.get('new_body_name', f'{src_name}_Mirror')
        plane    = params.get('plane', 'xy')
        src      = self._find(doc, src_name)

        normals = {'xy': FreeCAD.Vector(0,0,1), 'xz': FreeCAD.Vector(0,1,0), 'yz': FreeCAD.Vector(1,0,0)}
        normal = normals[plane]
        mirrored_shape = src.Shape.mirror(FreeCAD.Vector(0, 0, 0), normal)
        cp        = doc.addObject("Part::Feature", new_name)
        cp.Label  = new_name
        cp.Shape  = mirrored_shape
        self._recompute_and_fit(doc)
        return {"body_name": new_name, "plane": plane}

    def _create_circular_pattern(self, params):
        doc       = self._doc()
        src_name  = params['source_body_name']
        aname     = params.get('axis', 'z')
        qty       = int(params.get('quantity', 4))
        total_ang = float(params.get('angle', 360.0))
        base_name = params.get('new_body_base_name', f'{src_name}_Circ')
        src       = self._find(doc, src_name)
        axes      = {'x': FreeCAD.Vector(1,0,0), 'y': FreeCAD.Vector(0,1,0), 'z': FreeCAD.Vector(0,0,1)}
        axis      = axes[aname]
        created   = [src_name]

        for i in range(1, qty):
            angle    = (total_ang / qty) * i
            cp_name  = f"{base_name}_{i}"
            cp       = doc.addObject("Part::Feature", cp_name)
            cp.Label = cp_name
            shape    = src.Shape.copy()
            rot      = FreeCAD.Rotation(axis, angle)
            shape.Placement = FreeCAD.Placement(FreeCAD.Vector(), rot) * shape.Placement
            cp.Shape = shape
            created.append(cp_name)

        self._recompute_and_fit(doc)
        return {"created": created, "quantity": qty}

    def _create_rectangular_pattern(self, params):
        doc       = self._doc()
        src_name  = params['source_body_name']
        qty1      = int(params.get('quantity_one', 2))
        dist1     = float(params.get('distance_one', 10))
        ax1       = params.get('direction_one_axis', 'x')
        qty2      = int(params.get('quantity_two', 1))
        dist2     = float(params.get('distance_two', 10))
        ax2       = params.get('direction_two_axis', 'y')
        base_name = params.get('new_body_base_name', f'{src_name}_Rect')
        src       = self._find(doc, src_name)
        axes      = {'x': FreeCAD.Vector(1,0,0), 'y': FreeCAD.Vector(0,1,0), 'z': FreeCAD.Vector(0,0,1)}
        d1        = axes[ax1]
        d2        = axes[ax2]
        created   = []
        count     = 0

        for i in range(qty1):
            for j in range(qty2):
                if i == 0 and j == 0:
                    created.append(src_name)
                    count += 1
                    continue
                cp_name  = f"{base_name}_{count}"
                cp       = doc.addObject("Part::Feature", cp_name)
                cp.Label = cp_name
                offset   = FreeCAD.Vector(
                    d1.x * dist1 * i + d2.x * dist2 * j,
                    d1.y * dist1 * i + d2.y * dist2 * j,
                    d1.z * dist1 * i + d2.z * dist2 * j,
                )
                shape = src.Shape.copy()
                shape.Placement = FreeCAD.Placement(offset, FreeCAD.Rotation()) * shape.Placement
                cp.Shape = shape
                created.append(cp_name)
                count += 1

        self._recompute_and_fit(doc)
        return {"created": created, "quantity": count}

    # ------------------------------------------------------------------ info
    def _get_all_bodies(self, params):
        doc    = self._doc()
        bodies = [
            {"name": o.Label, "type": o.TypeId, "visible": o.Visibility}
            for o in doc.Objects if hasattr(o, 'Shape')
        ]
        return {"bodies": bodies, "count": len(bodies)}

    def _get_bounding_box(self, params):
        obj = self._find(self._doc(), params['body_name'])
        bb  = obj.Shape.BoundBox
        return {
            "xmin": bb.XMin, "ymin": bb.YMin, "zmin": bb.ZMin,
            "xmax": bb.XMax, "ymax": bb.YMax, "zmax": bb.ZMax,
            "xlen": bb.XLength, "ylen": bb.YLength, "zlen": bb.ZLength,
        }

    def _get_body_dimensions(self, params):
        obj = self._find(self._doc(), params['body_name'])
        bb  = obj.Shape.BoundBox
        return {
            "width":     bb.XLength,
            "depth":     bb.YLength,
            "height":    bb.ZLength,
            "volume":    obj.Shape.Volume,
            "area":      obj.Shape.Area,
            "num_faces": len(obj.Shape.Faces),
            "num_edges": len(obj.Shape.Edges),
        }

    def _get_faces_info(self, params):
        obj   = self._find(self._doc(), params['body_name'])
        faces = [
            {
                "index":        i,
                "area":         f.Area,
                "surface_type": type(f.Surface).__name__,
                "center":       [f.CenterOfMass.x, f.CenterOfMass.y, f.CenterOfMass.z],
            }
            for i, f in enumerate(obj.Shape.Faces)
        ]
        return {"faces": faces, "count": len(faces)}

    def _get_edges_info(self, params):
        obj   = self._find(self._doc(), params['body_name'])
        edges = [
            {"index": i, "length": e.Length, "curve_type": type(e.Curve).__name__}
            for i, e in enumerate(obj.Shape.Edges)
        ]
        return {"edges": edges, "count": len(edges)}

    # ------------------------------------------------------------------ export / save
    def _export_file(self, params):
        doc    = self._doc()
        fmt    = params.get('format', 'step').lower()
        fname  = params.get('filename', f'export.{fmt}')
        bname  = params.get('body_name', None)

        if not os.path.isabs(fname):
            fname = os.path.join(os.path.expanduser("~"), "Documents", fname)

        objs = [self._find(doc, bname)] if bname else [o for o in doc.Objects if hasattr(o, 'Shape')]

        if fmt == 'step':
            import Import
            Import.export(objs, fname)
        elif fmt in ('stl', 'obj'):
            import Mesh
            Mesh.export(objs, fname)
        elif fmt == 'fcstd':
            doc.saveAs(fname)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        return {"exported_to": fname, "format": fmt, "objects": len(objs)}

    def _save_document(self, params):
        doc   = self._doc()
        fname = params.get('filename', None)
        if fname:
            doc.saveAs(fname)
        else:
            doc.save()
        return {"saved": doc.FileName}

    # ------------------------------------------------------------------ new shapes
    def _create_half_torus(self, params):
        doc   = self._doc()
        r1    = float(params.get('major_radius', 30))
        r2    = float(params.get('minor_radius', 10))
        sweep = float(params.get('sweep_angle', 180))
        name  = params.get('body_name', 'HalfTorus')
        cx    = float(params.get('cx', 0))
        cy    = float(params.get('cy', 0))
        cz    = float(params.get('cz', 0))

        obj = doc.addObject("Part::Torus", name)
        obj.Label   = name
        obj.Radius1 = r1
        obj.Radius2 = r2
        obj.Angle3  = sweep
        obj.Placement = FreeCAD.Placement(FreeCAD.Vector(cx, cy, cz), FreeCAD.Rotation())
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "major_radius": r1, "minor_radius": r2, "sweep_angle": sweep}

    def _shell_body(self, params):
        doc          = self._doc()
        name         = params['body_name']
        thickness    = float(params.get('thickness', 2))
        face_indices = self._parse_list(params.get('face_indices', [0]), int)
        new_name     = params.get('new_body_name', f'{name}_Shell')
        obj          = self._find(doc, name)

        faces        = [obj.Shape.Faces[i] for i in face_indices]
        shell_shape  = obj.Shape.makeThickness(faces, -thickness, 1e-3)
        result       = doc.addObject("Part::Feature", new_name)
        result.Label = new_name
        result.Shape = shell_shape
        obj.Visibility = False
        self._recompute_and_fit(doc)
        face_names = [f"Face{i + 1}" for i in face_indices]
        return {"body_name": result.Label, "thickness": thickness, "open_faces": face_names}

    # ------------------------------------------------------------------ measurement
    def _get_body_center(self, params):
        obj   = self._find(self._doc(), params['body_name'])
        bb    = obj.Shape.BoundBox
        shape = obj.Shape
        # Compound には CenterOfMass がないので Solids/Shells から取得
        if not hasattr(shape, 'CenterOfMass') or shape.ShapeType == 'Compound':
            solids = shape.Solids
            if solids:
                shape = solids[0] if len(solids) == 1 else shape.fuse(solids[1:])
        try:
            com = shape.CenterOfMass
            com_list = [com.x, com.y, com.z]
        except Exception:
            com_list = [(bb.XMin + bb.XMax) / 2,
                        (bb.YMin + bb.YMax) / 2,
                        (bb.ZMin + bb.ZMax) / 2]
        return {
            "center_of_mass":   com_list,
            "geometric_center": [(bb.XMin + bb.XMax) / 2,
                                  (bb.YMin + bb.YMax) / 2,
                                  (bb.ZMin + bb.ZMax) / 2],
        }

    def _get_mass_properties(self, params):
        obj        = self._find(self._doc(), params['body_name'])
        density    = float(params.get('density', 1.0))
        shape      = obj.Shape
        vol_mm3    = shape.Volume
        vol_cm3    = vol_mm3 / 1000.0
        mass       = vol_cm3 * density
        try:
            com = shape.CenterOfMass
        except Exception:
            solids = shape.Solids
            com = solids[0].CenterOfMass if solids else shape.BoundBox.Center
        return {
            "volume_mm3":    vol_mm3,
            "volume_cm3":    vol_cm3,
            "area_mm2":      obj.Shape.Area,
            "density_g_cm3": density,
            "mass_g":        mass,
            "center_of_mass": [com.x, com.y, com.z],
        }

    def _measure_distance(self, params):
        doc  = self._doc()
        obj1 = self._find(doc, params['body1'])
        obj2 = self._find(doc, params['body2'])
        d, pts, _ = obj1.Shape.distToShape(obj2.Shape)
        p1, p2 = pts[0]
        return {
            "min_distance": d,
            "point1": [p1.x, p1.y, p1.z],
            "point2": [p2.x, p2.y, p2.z],
        }

    def _measure_angle(self, params):
        doc       = self._doc()
        obj1      = self._find(doc, params['body1'])
        obj2      = self._find(doc, params['body2'])
        fi1       = int(params.get('face_index1', 0))
        fi2       = int(params.get('face_index2', 0))
        face1     = obj1.Shape.Faces[fi1]
        face2     = obj2.Shape.Faces[fi2]

        def _normal(face):
            try:
                uv = face.Surface.parameter(face.CenterOfMass)
                return face.normalAt(*uv)
            except Exception:
                return face.normalAt(0.5, 0.5)

        n1    = _normal(face1)
        n2    = _normal(face2)
        cos_a = max(-1.0, min(1.0, n1.dot(n2) / (n1.Length * n2.Length)))
        angle = math.degrees(math.acos(cos_a))
        return {
            "angle_degrees": angle,
            "body1": obj1.Label, "face_index1": fi1,
            "body2": obj2.Label, "face_index2": fi2,
        }

    # ------------------------------------------------------------------ boolean selection
    def _combine_selection(self, params):
        doc      = self._doc()
        names    = self._parse_list(params['body_names'])
        op_raw   = params['operation']
        op, fc_op = self._normalize_boolean_operation(op_raw)
        new_name = params.get('new_body_name', f'{op}_result')
        if len(names) < 2:
            raise ValueError("body_names must contain at least 2 items.")

        base   = self._find(doc, names[0])
        tool   = self._find(doc, names[1])
        result = doc.addObject(fc_op, "_csel_0")
        result.Base = base
        result.Tool = tool
        base.Visibility = False
        tool.Visibility = False
        doc.recompute()

        for i, n in enumerate(names[2:], 1):
            tool       = self._find(doc, n)
            new_result = doc.addObject(fc_op, f"_csel_{i}")
            new_result.Base = result
            new_result.Tool = tool
            result.Visibility = False
            tool.Visibility   = False
            doc.recompute()
            result = new_result

        result.Label = new_name
        self._recompute_and_fit(doc)
        return {"body_name": result.Label, "operation": op, "count": len(names)}

    def _combine_selection_all(self, params):
        doc     = self._doc()
        op      = params.get('operation', 'join')
        new_name = params.get('new_body_name', f'All_{op}')
        visible = [o for o in doc.Objects if hasattr(o, 'Shape') and o.Visibility]
        if len(visible) < 2:
            raise ValueError("At least two visible solids are required.")
        return self._combine_selection({
            'body_names':   [o.Label for o in visible],
            'operation':    op,
            'new_body_name': new_name,
        })

    # ------------------------------------------------------------------ interference
    def _check_interference(self, params):
        doc  = self._doc()
        obj1 = self._find(doc, params['body1'])
        obj2 = self._find(doc, params['body2'])
        common = obj1.Shape.common(obj2.Shape)
        return {
            "has_interference":    common.Volume > 1e-6,
            "interference_volume": common.Volume,
            "body1": obj1.Label,
            "body2": obj2.Label,
        }

    def _get_body_relationships(self, params):
        doc  = self._doc()
        obj1 = self._find(doc, params['body1'])
        obj2 = self._find(doc, params['body2'])
        d, pts, _ = obj1.Shape.distToShape(obj2.Shape)
        common = obj1.Shape.common(obj2.Shape)
        return {
            "min_distance":  d,
            "intersecting":  common.Volume > 1e-6,
            "body1": obj1.Label,
            "body2": obj2.Label,
        }

    # ------------------------------------------------------------------ sketch
    def _create_sketch(self, params):
        doc   = self._doc()
        name  = params.get('sketch_name', 'Sketch')
        plane = params.get('plane', 'xy')
        cx    = float(params.get('cx', 0))
        cy    = float(params.get('cy', 0))
        cz    = float(params.get('cz', 0))

        rotations = {
            'xy': FreeCAD.Rotation(),
            'xz': FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90),
            'yz': FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90),
        }
        sketch = doc.addObject("Sketcher::SketchObject", name)
        sketch.Label = name
        sketch.Placement = FreeCAD.Placement(
            FreeCAD.Vector(cx, cy, cz),
            rotations.get(plane, FreeCAD.Rotation()))
        doc.recompute()
        return {"sketch_name": sketch.Label, "plane": plane}

    def _draw_line_in_sketch(self, params):
        doc    = self._doc()
        sketch = self._find(doc, params['sketch_name'])
        x1, y1 = float(params.get('x1', 0)),  float(params.get('y1', 0))
        x2, y2 = float(params.get('x2', 10)), float(params.get('y2', 0))
        idx = sketch.addGeometry(Part.LineSegment(
            FreeCAD.Vector(x1, y1, 0), FreeCAD.Vector(x2, y2, 0)))
        doc.recompute()
        return {"sketch_name": sketch.Label, "edge_index": idx}

    def _draw_circle_in_sketch(self, params):
        doc    = self._doc()
        sketch = self._find(doc, params['sketch_name'])
        cx     = float(params.get('cx', 0))
        cy     = float(params.get('cy', 0))
        r      = float(params.get('radius', 10))
        idx = sketch.addGeometry(Part.Circle(
            FreeCAD.Vector(cx, cy, 0), FreeCAD.Vector(0, 0, 1), r))
        doc.recompute()
        return {"sketch_name": sketch.Label, "edge_index": idx}

    def _draw_rectangle_in_sketch(self, params):
        doc    = self._doc()
        sketch = self._find(doc, params['sketch_name'])
        x1, y1 = float(params.get('x1', 0)),  float(params.get('y1', 0))
        x2, y2 = float(params.get('x2', 10)), float(params.get('y2', 10))
        i0 = sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(x1,y1,0), FreeCAD.Vector(x2,y1,0)))
        i1 = sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(x2,y1,0), FreeCAD.Vector(x2,y2,0)))
        i2 = sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(x2,y2,0), FreeCAD.Vector(x1,y2,0)))
        i3 = sketch.addGeometry(Part.LineSegment(FreeCAD.Vector(x1,y2,0), FreeCAD.Vector(x1,y1,0)))
        doc.recompute()
        return {"sketch_name": sketch.Label, "edge_indices": [i0, i1, i2, i3]}

    # ------------------------------------------------------------------ constraints
    def _add_sketch_constraint(self, constraint_type, params):
        import Sketcher
        doc    = self._doc()
        sketch = self._find(doc, params['sketch_name'])

        if constraint_type in ('Horizontal', 'Vertical'):
            sketch.addConstraint(Sketcher.Constraint(constraint_type, int(params['edge_index'])))
        elif constraint_type in ('Parallel', 'Perpendicular', 'Tangent'):
            sketch.addConstraint(Sketcher.Constraint(constraint_type, int(params['edge1']), int(params['edge2'])))
        elif constraint_type == 'Coincident':
            sketch.addConstraint(Sketcher.Constraint('Coincident',
                int(params['edge1']), int(params.get('point1', 1)),
                int(params['edge2']), int(params.get('point2', 1))))
        elif constraint_type == 'Distance':
            sketch.addConstraint(Sketcher.Constraint('Distance', int(params['edge_index']), float(params['distance'])))
        elif constraint_type == 'Radius':
            sketch.addConstraint(Sketcher.Constraint('Radius', int(params['edge_index']), float(params['radius'])))

        doc.recompute()
        return {"sketch_name": sketch.Label, "constraint": constraint_type}

    def _add_coincident_constraint(self, params):
        return self._add_sketch_constraint('Coincident', params)

    def _add_horizontal_constraint(self, params):
        return self._add_sketch_constraint('Horizontal', params)

    def _add_vertical_constraint(self, params):
        return self._add_sketch_constraint('Vertical', params)

    def _add_parallel_constraint(self, params):
        return self._add_sketch_constraint('Parallel', params)

    def _add_perpendicular_constraint(self, params):
        return self._add_sketch_constraint('Perpendicular', params)

    def _add_tangent_constraint(self, params):
        return self._add_sketch_constraint('Tangent', params)

    def _add_linear_dimension(self, params):
        return self._add_sketch_constraint('Distance', params)

    def _add_radius_dimension(self, params):
        return self._add_sketch_constraint('Radius', params)

    # ------------------------------------------------------------------ sketch 鬯ｩ蛹・ｽｽ・ｶ鬩怜遜・ｽ・ｫ驛｢譎｢・ｽ・ｻsolid
    def _extrude_sketch(self, params):
        doc       = self._doc()
        sketch    = self._find(doc, params['sketch_name'])
        length    = float(params.get('length', 10))
        symmetric = params.get('symmetric', False)
        name      = params.get('body_name', f'{sketch.Label}_Extrude')

        extrude            = doc.addObject("Part::Extrusion", name)
        extrude.Label      = name
        extrude.Base       = sketch
        extrude.DirMode    = 'Normal'
        extrude.LengthFwd  = length
        extrude.LengthRev  = length if symmetric else 0
        extrude.Solid      = True
        extrude.Symmetric  = symmetric
        sketch.Visibility  = False
        self._recompute_and_fit(doc)
        return {"body_name": extrude.Label, "length": length, "symmetric": symmetric}

    def _revolve_sketch(self, params):
        doc    = self._doc()
        sketch = self._find(doc, params['sketch_name'])
        angle  = float(params.get('angle', 360))
        aname  = params.get('axis', 'y')
        name   = params.get('body_name', f'{sketch.Label}_Revolve')
        axes   = {'x': FreeCAD.Vector(1,0,0), 'y': FreeCAD.Vector(0,1,0), 'z': FreeCAD.Vector(0,0,1)}

        revolve         = doc.addObject("Part::Revolution", name)
        revolve.Label   = name
        revolve.Source  = sketch
        revolve.Axis    = axes[aname]
        revolve.Base    = FreeCAD.Vector(0, 0, 0)
        revolve.Angle   = angle
        revolve.Solid   = True
        sketch.Visibility = False
        self._recompute_and_fit(doc)
        return {"body_name": revolve.Label, "angle": angle, "axis": aname}

    def _sweep_sketch(self, params):
        doc     = self._doc()
        profile = self._find(doc, params['profile_sketch'])
        path    = self._find(doc, params['path_sketch'])
        name    = params.get('body_name', f'{profile.Label}_Sweep')

        sweep          = doc.addObject("Part::Sweep", name)
        sweep.Label    = name
        sweep.Sections = [profile]
        sweep.Spine    = (path, ['Edge1'])
        sweep.Solid    = True
        sweep.Frenet   = params.get('frenet', True)
        profile.Visibility = False
        self._recompute_and_fit(doc)
        return {"body_name": sweep.Label}

    def _loft_sketches(self, params):
        doc      = self._doc()
        names    = self._parse_list(params['sketch_names'])
        name     = params.get('body_name', 'Loft')
        sections = [self._find(doc, n) for n in names]

        loft          = doc.addObject("Part::Loft", name)
        loft.Label    = name
        loft.Sections = sections
        loft.Solid    = True
        loft.Ruled    = params.get('ruled', False)
        loft.Closed   = params.get('closed', False)
        for s in sections:
            s.Visibility = False
        self._recompute_and_fit(doc)
        return {"body_name": loft.Label, "sections": len(sections)}

    # ------------------------------------------------------------------ pipe
    def _create_pipe(self, params):
        doc    = self._doc()
        start  = FreeCAD.Vector(float(params.get('x1', 0)), float(params.get('y1', 0)), float(params.get('z1', 0)))
        end    = FreeCAD.Vector(float(params.get('x2', 0)), float(params.get('y2', 0)), float(params.get('z2', 50)))
        radius = float(params.get('radius', 5))
        name   = params.get('body_name', 'Pipe')

        direction = end.sub(start)
        length    = direction.Length
        if length < 1e-6:
            raise ValueError("Start point and end point must be different.")
        direction.normalize()

        shape      = Part.makeCylinder(radius, length, start, direction)
        obj        = doc.addObject("Part::Feature", name)
        obj.Label  = name
        obj.Shape  = shape
        self._recompute_and_fit(doc)
        return {"body_name": obj.Label, "radius": radius, "length": length}

    # ------------------------------------------------------------------ section
    def _create_section_view(self, params):
        doc      = self._doc()
        name     = params['body_name']
        plane    = params.get('plane', 'xy')
        offset   = float(params.get('offset', 0))
        new_name = params.get('new_body_name', f'{name}_Section')
        obj      = self._find(doc, name)

        bb   = obj.Shape.BoundBox
        size = max(bb.XLength, bb.YLength, bb.ZLength) * 2 + 200

        if plane == 'xy':
            cutter_shape = Part.makeBox(size, size, size,
                FreeCAD.Vector(-size/2, -size/2, offset))
        elif plane == 'xz':
            cutter_shape = Part.makeBox(size, size, size,
                FreeCAD.Vector(-size/2, offset, -size/2))
        else:  # yz
            cutter_shape = Part.makeBox(size, size, size,
                FreeCAD.Vector(offset, -size/2, -size/2))

        cutter_obj            = doc.addObject("Part::Feature", f"_{new_name}_Cutter")
        cutter_obj.Shape      = cutter_shape
        cutter_obj.Visibility = False

        section       = doc.addObject("Part::Cut", new_name)
        section.Label = new_name
        section.Base  = obj
        section.Tool  = cutter_obj
        obj.Visibility = False
        self._recompute_and_fit(doc)
        return {"body_name": section.Label, "plane": plane, "offset": offset}

    # ------------------------------------------------------------------ undo/redo
    def _undo(self, params):
        doc = self._doc()
        doc.undo()
        self._fit_view()
        return {"status": "undo executed"}

    def _redo(self, params):
        doc = self._doc()
        doc.redo()
        self._fit_view()
        return {"status": "redo executed"}

    # ------------------------------------------------------------------ util
    def _delete_all_features(self, params):
        doc   = self._doc()
        objs  = list(doc.Objects)
        deleted = 0
        for o in objs:
            if o.Name:
                doc.removeObject(o.Name)
                deleted += 1
        doc.recompute()
        return {"deleted_count": deleted}

    def _execute_macro(self, params):
        commands = params.get('commands', [])
        results  = []
        for cmd in commands:
            r = self._dispatch(cmd['tool_name'], cmd.get('arguments', {}))
            results.append({"tool": cmd['tool_name'], "result": r})
        return {"executed": len(results), "results": results}


# ---- 鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｨ鬯ｩ蟷｢・ｽ・｢髫ｴ雜｣・ｽ・｢郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｳ鬯ｩ蟷｢・ｽ・｢髫ｴ荳ｻ繝ｻ隶捺ｺ倥・陷ｿ謔ｶ貂夂ｹ晢ｽｻ繝ｻ・ｹ髫ｴ雜｣・ｽ・｢郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｼ鬯ｩ蟷｢・ｽ・｢髫ｴ蠑ｱ繝ｻ繝ｻ・ｺ繝ｻ・｢鬩搾ｽｵ繝ｻ・ｺ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｹ髫ｴ雜｣・ｽ・｢郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｳ鬯ｩ蟷｢・ｽ・｢髫ｴ蟇よ升邵ｺ迢暦ｽｹ譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｼ鬮ｯ蜈ｷ・ｽ・ｹ郢晢ｽｻ繝ｻ・ｻ鬩幢ｽ｢隴趣ｽ｢繝ｻ・ｽ繝ｻ・ｻ鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｯ鬯ｩ蟷｢・ｽ・｢髫ｴ雜｣・ｽ・｢郢晢ｽｻ繝ｻ・ｽ郢晢ｽｻ繝ｻ・ｭ鬯ｮ・ｯ隶厄ｽｸ繝ｻ・ｽ繝ｻ・ｳ鬮ｮ荵昴・繝ｻ・ｽ繝ｻ・ｯ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・｡鬮ｫ・ｴ繝ｻ・ｴ郢晢ｽｻ繝ｻ・ｧ鬮ｯ・ｷ郢晢ｽｻ繝ｻ・ｽ繝ｻ・ｾ鬯ｩ謳ｾ・ｽ・ｵ郢晢ｽｻ繝ｻ・ｺ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｫ鬯ｮ・ｯ繝ｻ・ｷ郢晢ｽｻ繝ｻ・ｻ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｼ鬯ｩ謳ｾ・ｽ・ｵ郢晢ｽｻ繝ｻ・ｺ驛｢譎｢・ｽ・ｻ郢晢ｽｻ繝ｻ・ｰ鬯ｩ蟷｢・ｽ・｢郢晢ｽｻ繝ｻ・ｧ鬮ｯ貊灘擠繝ｻ・ｯ闔ｨ螟ｲ・ｽ・ｽ繝ｻ・ｽ髣包ｽｵ隴擾ｽｴ郢晢ｽｻ鬩幢ｽ｢隴趣ｽ｢繝ｻ・ｽ繝ｻ・ｻ---
_addon_instance = None

def start_addon():
    global _addon_instance
    if _addon_instance is not None:
        _addon_instance.stop()
    elif _is_existing_mcp_server_alive(API_HOST, API_PORT):
        FreeCAD.Console.PrintWarning(
            f"[MCP] Existing MCP server detected at http://{API_HOST}:{API_PORT}/health. "
            f"Skipping duplicate addon startup.\n"
        )
        return

    try:
        _addon_instance = FreeCADMCPAddon()
    except Exception as e:
        _addon_instance = None
        FreeCAD.Console.PrintError(f"[MCP] Failed to start addon: {e}\n")

start_addon()
