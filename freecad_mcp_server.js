#!/usr/bin/env node
// freecad_mcp_server.js - FreeCAD MCP Server v0.9.0
import http from 'http';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
    CallToolRequestSchema,
    ErrorCode,
    ListToolsRequestSchema,
    McpError,
} from '@modelcontextprotocol/sdk/types.js';

const logDebug = (message, ...args) => {
    console.error(`[FREECAD-MCP] ${new Date().toISOString()} - ${message}`, ...args);
};

const freecadApiHost = process.env.FREECAD_MCP_HOST || '127.0.0.1';
const freecadApiPort = Number(process.env.FREECAD_MCP_PORT || 8765);
const freecadApiPath = '/command';

// 共通プロパティ
const BODY_NAME = { type: 'string', description: 'Body name' };
const NUM = (desc, def) => ({ anyOf: [{ type: 'number' }, { type: 'string' }], description: desc, default: def });
const STR = (desc, def) => ({ type: 'string', description: desc, ...(def !== undefined ? { default: def } : {}) });
const PLACEMENT_PROPS = {
    cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
    x_placement: STR('left|center|right', 'center'),
    y_placement: STR('front|center|back', 'center'),
    z_placement: STR('bottom|center|top', 'center'),
};

const TOOL_SCHEMAS = {
    execute_macro: {
        commands: { anyOf: [{ type: 'array', items: { type: 'object' } }, { type: 'string' }], description: 'List of {tool_name, arguments}' },
    },
    create_box: {
        body_name: BODY_NAME,
        width: NUM('Width (mm)', 50), depth: NUM('Depth (mm)', 30), height: NUM('Height (mm)', 20),
        ...PLACEMENT_PROPS,
    },
    create_cube: {
        body_name: BODY_NAME, size: NUM('Side length (mm)', 50), ...PLACEMENT_PROPS,
    },
    create_cylinder: {
        body_name: BODY_NAME,
        radius: NUM('Radius (mm)', 25), height: NUM('Height (mm)', 50),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
        z_placement: STR('bottom|center|top', 'center'),
    },
    create_sphere: {
        body_name: BODY_NAME, radius: NUM('Radius (mm)', 25),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
    },
    create_cone: {
        body_name: BODY_NAME,
        radius: NUM('Bottom radius (mm)', 25), radius2: NUM('Top radius (mm)', 0),
        height: NUM('Height (mm)', 50),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
        z_placement: STR('bottom|center|top', 'bottom'),
    },
    create_torus: {
        body_name: BODY_NAME,
        major_radius: NUM('Major radius (mm)', 30), minor_radius: NUM('Minor radius (mm)', 10),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
    },
    create_hemisphere: {
        body_name: BODY_NAME, radius: NUM('Radius (mm)', 25),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
        orientation: STR('positive|negative', 'positive'),
    },
    create_half_torus: {
        body_name: BODY_NAME,
        major_radius: NUM('Major radius (mm)', 30), minor_radius: NUM('Minor radius (mm)', 10),
        sweep_angle: NUM('Sweep angle (deg)', 180),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
    },
    create_polygon_prism: {
        body_name: BODY_NAME,
        num_sides: NUM('Number of sides', 6), radius: NUM('Circumradius (mm)', 25),
        height: NUM('Height (mm)', 50),
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), cz: NUM('Center Z', 0),
        z_placement: STR('bottom|center|top', 'bottom'),
    },
    combine_by_name: {
        target_body: { type: 'string', description: 'Base body name' },
        tool_body: { type: 'string', description: 'Tool body name' },
        operation: STR('join|cut|intersect'),
        new_body_name: BODY_NAME,
    },
    combine_selection: {
        body_names: { anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'string' }], description: 'List of body names (array or JSON string)' },
        operation: STR('join|cut|intersect'),
        new_body_name: BODY_NAME,
    },
    combine_selection_all: {
        operation: STR('join|cut|intersect'),
        new_body_name: BODY_NAME,
    },
    move_by_name: {
        body_name: BODY_NAME,
        x_dist: NUM('X distance (mm)', 0), y_dist: NUM('Y distance (mm)', 0), z_dist: NUM('Z distance (mm)', 0),
    },
    rotate_by_name: {
        body_name: BODY_NAME,
        axis: STR('x|y|z', 'z'), angle: NUM('Angle (deg)', 90),
        cx: NUM('Pivot X', 0), cy: NUM('Pivot Y', 0), cz: NUM('Pivot Z', 0),
    },
    add_fillet: {
        body_name: BODY_NAME, radius: NUM('Fillet radius (mm)', 1),
        edge_indices: { anyOf: [{ type: 'array', items: { type: 'integer' } }, { type: 'string' }], description: 'Edge indices (empty=all, array or JSON string)' },
    },
    add_chamfer: {
        body_name: BODY_NAME, distance: NUM('Chamfer distance (mm)', 1),
        edge_indices: { anyOf: [{ type: 'array', items: { type: 'integer' } }, { type: 'string' }], description: 'Edge indices (empty=all, array or JSON string)' },
    },
    shell_body: {
        body_name: BODY_NAME, thickness: NUM('Wall thickness (mm)', 2),
        face_indices: { anyOf: [{ type: 'array', items: { type: 'integer' } }, { type: 'string' }], description: 'Face indices to open (array or JSON string)' },
        new_body_name: BODY_NAME,
    },
    hide_body: { body_name: BODY_NAME },
    show_body: { body_name: BODY_NAME },
    copy_body_symmetric: {
        source_body_name: BODY_NAME, new_body_name: BODY_NAME,
        plane: STR('xy|xz|yz', 'xy'),
    },
    create_circular_pattern: {
        source_body_name: BODY_NAME, new_body_base_name: BODY_NAME,
        axis: STR('x|y|z', 'z'), quantity: NUM('Count', 4), angle: NUM('Total angle (deg)', 360),
    },
    create_rectangular_pattern: {
        source_body_name: BODY_NAME, new_body_base_name: BODY_NAME,
        quantity_one: NUM('Count in direction 1', 2), distance_one: NUM('Distance 1 (mm)', 10),
        direction_one_axis: STR('x|y|z', 'x'),
        quantity_two: NUM('Count in direction 2', 1), distance_two: NUM('Distance 2 (mm)', 10),
        direction_two_axis: STR('x|y|z', 'y'),
    },
    get_all_bodies: {},
    get_bounding_box: { body_name: BODY_NAME },
    get_body_dimensions: { body_name: BODY_NAME },
    get_body_center: { body_name: BODY_NAME },
    get_faces_info: { body_name: BODY_NAME },
    get_edges_info: { body_name: BODY_NAME },
    get_mass_properties: { body_name: BODY_NAME, density: NUM('Density (g/cm³)', 1.0) },
    get_body_relationships: {
        body1: { type: 'string', description: 'First body name' },
        body2: { type: 'string', description: 'Second body name' },
    },
    check_interference: {
        body1: { type: 'string', description: 'First body name' },
        body2: { type: 'string', description: 'Second body name' },
    },
    measure_distance: {
        body1: { type: 'string', description: 'First body name' },
        body2: { type: 'string', description: 'Second body name' },
    },
    measure_angle: {
        body1: { type: 'string' }, body2: { type: 'string' },
        face_index1: NUM('Face index for body1', 0), face_index2: NUM('Face index for body2', 0),
    },
    export_file: {
        body_name: BODY_NAME, format: STR('step|stl|obj|fcstd', 'step'), filename: STR('Output filename'),
    },
    delete_all_features: {},
    save_document: { filename: STR('Save path (optional)') },
    create_sketch: {
        sketch_name: STR('Sketch name', 'Sketch'),
        plane: STR('xy|xz|yz', 'xy'),
        cx: NUM('X offset', 0), cy: NUM('Y offset', 0), cz: NUM('Z offset', 0),
    },
    draw_line_in_sketch: {
        sketch_name: BODY_NAME,
        x1: NUM('Start X', 0), y1: NUM('Start Y', 0), x2: NUM('End X', 10), y2: NUM('End Y', 0),
    },
    draw_circle_in_sketch: {
        sketch_name: BODY_NAME,
        cx: NUM('Center X', 0), cy: NUM('Center Y', 0), radius: NUM('Radius', 10),
    },
    draw_rectangle_in_sketch: {
        sketch_name: BODY_NAME,
        x1: NUM('Corner X1', 0), y1: NUM('Corner Y1', 0), x2: NUM('Corner X2', 10), y2: NUM('Corner Y2', 10),
    },
    add_coincident_constraint: {
        sketch_name: BODY_NAME,
        edge1: NUM('First geometry index', 0), edge2: NUM('Second geometry index', 1),
        point1: NUM('Vertex on first edge (1=start, 2=end)', 1),
        point2: NUM('Vertex on second edge (1=start, 2=end)', 1),
    },
    add_horizontal_constraint: { sketch_name: BODY_NAME, edge_index: NUM('Geometry index', 0) },
    add_vertical_constraint:   { sketch_name: BODY_NAME, edge_index: NUM('Geometry index', 0) },
    add_parallel_constraint:   { sketch_name: BODY_NAME, edge1: NUM('First geometry index', 0), edge2: NUM('Second geometry index', 1) },
    add_perpendicular_constraint: { sketch_name: BODY_NAME, edge1: NUM('First geometry index', 0), edge2: NUM('Second geometry index', 1) },
    add_tangent_constraint:    { sketch_name: BODY_NAME, edge1: NUM('First geometry index', 0), edge2: NUM('Second geometry index', 1) },
    add_linear_dimension: {
        sketch_name: BODY_NAME, edge_index: NUM('Geometry index', 0),
        distance: NUM('Dimension value (mm)', 10),
    },
    add_radius_dimension: { sketch_name: BODY_NAME, edge_index: NUM('Geometry index', 0), radius: NUM('Radius value (mm)', 10) },
    extrude_sketch: {
        sketch_name: BODY_NAME, body_name: BODY_NAME,
        length: NUM('Extrusion length (mm)', 10), symmetric: { type: 'boolean', default: false },
    },
    revolve_sketch: {
        sketch_name: BODY_NAME, body_name: BODY_NAME,
        axis: STR('x|y|z', 'z'), angle: NUM('Revolve angle (deg)', 360),
    },
    sweep_sketch: {
        profile_sketch: STR('Profile sketch name'), path_sketch: STR('Path sketch name'),
        body_name: BODY_NAME,
    },
    loft_sketches: {
        sketch_names: { anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'string' }], description: 'Ordered list of sketch names (array or JSON string)' },
        body_name: BODY_NAME, ruled: { type: 'boolean', default: false },
    },
    create_pipe: {
        body_name: BODY_NAME,
        x1: NUM('Start X', 0), y1: NUM('Start Y', 0), z1: NUM('Start Z', 0),
        x2: NUM('End X', 0),   y2: NUM('End Y', 0),   z2: NUM('End Z', 50),
        radius: NUM('Pipe radius (mm)', 5),
    },
    create_section_view: {
        body_name: BODY_NAME, new_body_name: BODY_NAME,
        plane: STR('xy|xz|yz', 'xy'), offset: NUM('Section offset (mm)', 0),
    },
};

const TOOL_NAMES = Object.keys(TOOL_SCHEMAS);

class FreeCADMCPServer {
    constructor() {
        logDebug('Initializing FreeCAD MCP Server...');
        this.server = new Server(
            { name: 'freecad-mcp-server', version: '1.1.0' },
            { capabilities: { tools: {} } }
        );
        this.setupToolHandlers();
    }

    async sendCommand(command, parameters, timeout = 60000) {
        const payload = JSON.stringify({
            command,
            parameters: parameters || {},
            timeout_ms: timeout,
        });

        return await new Promise((resolve, reject) => {
            const req = http.request(
                {
                    host: freecadApiHost,
                    port: freecadApiPort,
                    path: freecadApiPath,
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Content-Length': Buffer.byteLength(payload),
                    },
                    timeout,
                },
                (res) => {
                    let body = '';
                    res.setEncoding('utf8');
                    res.on('data', (chunk) => {
                        body += chunk;
                    });
                    res.on('end', () => {
                        if (res.statusCode < 200 || res.statusCode >= 300) {
                            reject(new Error(`FreeCAD API HTTP ${res.statusCode}: ${body}`));
                            return;
                        }
                        try {
                            resolve(JSON.parse(body));
                        } catch (_) {
                            reject(new Error('FreeCAD API response is not valid JSON.'));
                        }
                    });
                }
            );

            req.on('timeout', () => {
                req.destroy(new Error(`FreeCAD API timeout (${timeout}ms). FreeCAD add-on is running?`));
            });
            req.on('error', reject);
            req.write(payload);
            req.end();
        });
    }

    setupToolHandlers() {
        this.server.setRequestHandler(ListToolsRequestSchema, async () => {
            const tools = TOOL_NAMES.map((name) => ({
                name,
                description: `FreeCAD tool: ${name}`,
                inputSchema: {
                    type: 'object',
                    properties: TOOL_SCHEMAS[name] || {},
                    additionalProperties: true,
                },
            }));
            return { tools };
        });

        this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
            const { name, arguments: args } = request.params;
            logDebug(`Tool called: ${name}`, args);

            if (!TOOL_NAMES.includes(name)) {
                throw new McpError(ErrorCode.InvalidParams, `Unknown tool: ${name}`);
            }

            try {
                const json = await this.sendCommand(name, args || {});
                if (json.status === 'error') {
                    throw new McpError(
                        ErrorCode.InternalError,
                        `FreeCAD Error [${name}]: ${json.message}\n\n${json.traceback || ''}`
                    );
                }

                let text = `FreeCAD command '${name}' executed successfully.`;
                if (json.result !== undefined) {
                    const result =
                        typeof json.result === 'object'
                            ? JSON.stringify(json.result, null, 2)
                            : String(json.result);
                    text += `\n\nResult:\n\
\`\`\`\n${result}\n\`\`\``;
                }
                return { content: [{ type: 'text', text }] };
            } catch (err) {
                if (err instanceof McpError) throw err;
                throw new McpError(ErrorCode.InternalError, `Command failed '${name}': ${err.message}`);
            }
        });
    }

    async run() {
        const transport = new StdioServerTransport();
        this.server.onerror = (e) => logDebug('Server error:', e);
        await this.server.connect(transport);
        logDebug(`FreeCAD MCP Server started. Target API: http://${freecadApiHost}:${freecadApiPort}${freecadApiPath}`);
    }
}

async function main() {
    const server = new FreeCADMCPServer();
    await server.run();
}

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
process.on('uncaughtException', (e) => {
    logDebug('Uncaught:', e);
    process.exit(1);
});
process.on('unhandledRejection', (e) => {
    logDebug('Unhandled:', e);
    process.exit(1);
});

main();