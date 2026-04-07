import fs from 'fs';
import path from 'path';

const HOST = process.env.FREECAD_MCP_HOST || '127.0.0.1';
const PORT = Number(process.env.FREECAD_MCP_PORT || 8765);
const BASE_URL = `http://${HOST}:${PORT}`;
const ROOT = process.cwd();

function extractToolNames() {
  const file = path.join(ROOT, 'freecad_mcp_server.js');
  const text = fs.readFileSync(file, 'utf8');
  const start = text.indexOf('const TOOL_SCHEMAS = {');
  const end = text.indexOf('};\n\nconst TOOL_NAMES', start);
  if (start === -1 || end === -1) {
    throw new Error('Could not locate TOOL_SCHEMAS in freecad_mcp_server.js');
  }

  const block = text.slice(start, end);
  const names = [];
  for (const line of block.split(/\r?\n/)) {
    const match = line.match(/^\s{4}([a-z0-9_]+):\s*\{/);
    if (match) {
      names.push(match[1]);
    }
  }
  return names;
}

async function healthcheck() {
  const response = await fetch(`${BASE_URL}/health`);
  if (!response.ok) {
    throw new Error(`Healthcheck failed with status ${response.status}`);
  }
  return response.json();
}

async function runCommand(command, params = {}, timeoutMs = 60000) {
  const response = await fetch(`${BASE_URL}/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, parameters: params, timeout_ms: timeoutMs }),
  });

  const payload = await response.json();
  if (!response.ok || !['ok', 'success'].includes(payload.status)) {
    const message = payload?.message || `HTTP ${response.status}`;
    const error = new Error(message);
    error.payload = payload;
    throw error;
  }
  return payload.result;
}

function ensure(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function includesAll(haystack, needles) {
  return needles.every((item) => haystack.includes(item));
}

const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
const fcstdPath = path.join(ROOT, `regression_all_tools_${timestamp}.fcstd`);
const stlPath = path.join(ROOT, `regression_comboAll_${timestamp}.stl`);

const usedTools = new Set();
const results = [];

async function step(name, tool, params, verify) {
  process.stdout.write(`RUN  ${tool} (${name})\n`);
  usedTools.add(tool);
  const result = await runCommand(tool, params);
  if (verify) {
    await verify(result);
  }
  results.push({ name, tool, ok: true });
  process.stdout.write(`PASS ${tool}\n`);
  return result;
}

async function main() {
  const toolNames = extractToolNames();
  await healthcheck();

  await step('reset', 'delete_all_features', {}, (r) => {
    ensure(typeof r.deleted_count === 'number', 'delete_all_features did not return deleted_count');
  });

  await step('create box', 'create_box', {
    body_name: 'boxA',
    width: '20',
    depth: '20',
    height: '20',
    cx: '0',
    cy: '0',
    cz: '0',
    x_placement: 'center',
    y_placement: 'center',
    z_placement: 'bottom',
  }, (r) => ensure(r.body_name === 'boxA', 'create_box returned unexpected body name'));

  await step('create cube', 'create_cube', {
    body_name: 'cubeA',
    size: '12',
    cx: '-30',
    cy: '0',
    cz: '0',
    x_placement: 'center',
    y_placement: 'center',
    z_placement: 'bottom',
  });

  await step('create cylinder', 'create_cylinder', {
    body_name: 'cylA',
    radius: '6',
    height: '30',
    cx: '0',
    cy: '0',
    cz: '0',
    z_placement: 'bottom',
  });

  await step('create sphere', 'create_sphere', {
    body_name: 'sphA',
    radius: '8',
    cx: '30',
    cy: '0',
    cz: '10',
  });

  await step('create cone', 'create_cone', {
    body_name: 'coneA',
    radius: '8',
    radius2: '3',
    height: '18',
    cx: '50',
    cy: '0',
    cz: '0',
    z_placement: 'bottom',
  });

  await step('create torus', 'create_torus', {
    body_name: 'torA',
    major_radius: '12',
    minor_radius: '3',
    cx: '0',
    cy: '35',
    cz: '10',
  });

  await step('create hemisphere', 'create_hemisphere', {
    body_name: 'hemiA',
    radius: '7',
    cx: '-45',
    cy: '20',
    cz: '7',
    orientation: 'positive',
  });

  await step('create half torus', 'create_half_torus', {
    body_name: 'htorA',
    major_radius: '10',
    minor_radius: '2',
    sweep_angle: '180',
    cx: '25',
    cy: '25',
    cz: '10',
  });

  await step('create polygon prism', 'create_polygon_prism', {
    body_name: 'polyA',
    num_sides: '6',
    radius: '7',
    height: '15',
    cx: '-20',
    cy: '25',
    cz: '0',
    z_placement: 'bottom',
  });

  await step('create pipe', 'create_pipe', {
    body_name: 'pipeA',
    radius: '2',
    x1: '-10',
    y1: '-30',
    z1: '0',
    x2: '20',
    y2: '-30',
    z2: '20',
  });

  await step('symmetric copy', 'copy_body_symmetric', {
    source_body_name: 'coneA',
    new_body_name: 'coneA_mirror',
    plane: 'yz',
  });

  await step('move body', 'move_by_name', {
    body_name: 'cubeA',
    x_dist: '5',
    y_dist: '0',
    z_dist: '0',
  });

  await step('rotate body', 'rotate_by_name', {
    body_name: 'cubeA',
    axis: 'z',
    angle: '30',
    cx: '0',
    cy: '0',
    cz: '0',
  });

  await step('fillet body', 'add_fillet', {
    body_name: 'boxA',
    radius: '1',
    edge_indices: '[]',
  }, (r) => ensure(r.body_name === 'boxA_Fillet', 'Unexpected fillet output name'));

  await step('chamfer body', 'add_chamfer', {
    body_name: 'cubeA',
    distance: '1',
    edge_indices: '[]',
  }, (r) => ensure(r.body_name === 'cubeA_Chamfer', 'Unexpected chamfer output name'));

  await step('shell body', 'shell_body', {
    body_name: 'polyA',
    new_body_name: 'polyA_shell',
    thickness: '1',
    face_indices: '[0]',
  });

  await step('hide body', 'hide_body', { body_name: 'sphA' });
  await step('show body', 'show_body', { body_name: 'sphA' });

  await step('circular pattern', 'create_circular_pattern', {
    source_body_name: 'coneA',
    new_body_base_name: 'conePat',
    axis: 'z',
    quantity: '4',
    angle: '360',
  }, (r) => ensure(r.created.length === 4, 'Circular pattern did not create four instances'));

  await step('rectangular pattern', 'create_rectangular_pattern', {
    source_body_name: 'sphA',
    new_body_base_name: 'sphGrid',
    direction_one_axis: 'x',
    distance_one: '20',
    quantity_one: '2',
    direction_two_axis: 'y',
    distance_two: '20',
    quantity_two: '2',
  }, (r) => ensure(r.created.length === 4, 'Rectangular pattern did not create four instances'));

  await step('combine by name', 'combine_by_name', {
    target_body: 'boxA_Fillet',
    tool_body: 'cylA',
    operation: 'join',
    new_body_name: 'comboJoin',
  });

  await step('combine selection', 'combine_selection', {
    body_names: '["cubeA_Chamfer","boxA_Fillet"]',
    operation: 'intersect',
    new_body_name: 'comboIntersect',
  });

  await step('combine selection all', 'combine_selection_all', {
    operation: 'join',
    new_body_name: 'comboAll',
  });

  await step('list bodies', 'get_all_bodies', {}, (r) => {
    ensure(r.count >= 10, 'Expected multiple bodies after creation sequence');
  });

  await step('bounding box', 'get_bounding_box', { body_name: 'comboAll' }, (r) => {
    ensure(r.xlen > 0 && r.ylen > 0 && r.zlen > 0, 'Bounding box dimensions must be positive');
  });

  await step('body dimensions', 'get_body_dimensions', { body_name: 'comboAll' }, (r) => {
    ensure(r.num_faces > 0 && r.num_edges > 0, 'Body dimensions should report faces and edges');
  });

  await step('body center', 'get_body_center', { body_name: 'comboAll' }, (r) => {
    ensure(Array.isArray(r.center_of_mass) && r.center_of_mass.length === 3, 'Missing center_of_mass');
  });

  await step('faces info', 'get_faces_info', { body_name: 'comboAll' }, (r) => {
    ensure(r.count > 0, 'Expected faces from comboAll');
  });

  await step('edges info', 'get_edges_info', { body_name: 'comboAll' }, (r) => {
    ensure(r.count > 0, 'Expected edges from comboAll');
    ensure(r.edges.some((edge) => typeof edge.curve_type === 'string'), 'Edges must contain curve_type');
  });

  await step('mass properties', 'get_mass_properties', {
    body_name: 'comboAll',
    density: '7.85',
  }, (r) => ensure(r.mass_g > 0, 'Mass should be positive'));

  await step('body relationships', 'get_body_relationships', {
    body1: 'boxA_Fillet',
    body2: 'comboJoin',
  }, (r) => ensure(typeof r.intersecting === 'boolean', 'Missing intersecting flag'));

  await step('interference check', 'check_interference', {
    body1: 'comboJoin',
    body2: 'comboIntersect',
  }, (r) => ensure(typeof r.has_interference === 'boolean', 'Missing interference flag'));

  await step('distance measure', 'measure_distance', {
    body1: 'boxA_Fillet',
    body2: 'sphA',
  }, (r) => ensure(r.min_distance >= 0, 'Distance must be non-negative'));

  await step('angle measure', 'measure_angle', {
    body1: 'boxA_Fillet',
    face_index1: '0',
    body2: 'cylA',
    face_index2: '0',
  }, (r) => ensure(Number.isFinite(r.angle_degrees), 'Angle must be finite'));

  await step('create sketch closed', 'create_sketch', {
    sketch_name: 'sk_ext',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch revolve', 'create_sketch', {
    sketch_name: 'sk_rev',
    plane: 'xz',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch path', 'create_sketch', {
    sketch_name: 'path1',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch profile', 'create_sketch', {
    sketch_name: 'prof1',
    plane: 'yz',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch loft A', 'create_sketch', {
    sketch_name: 'loftA',
    plane: 'xy',
    cx: '70',
    cy: '0',
    cz: '0',
  });
  await step('create sketch loft B', 'create_sketch', {
    sketch_name: 'loftB',
    plane: 'xy',
    cx: '70',
    cy: '0',
    cz: '20',
  });
  await step('create sketch horizontal', 'create_sketch', {
    sketch_name: 'sk_hv',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch vertical', 'create_sketch', {
    sketch_name: 'sk_v',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch parallel', 'create_sketch', {
    sketch_name: 'sk_par',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch perpendicular', 'create_sketch', {
    sketch_name: 'sk_perp',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch tangent', 'create_sketch', {
    sketch_name: 'sk_tan',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch radius', 'create_sketch', {
    sketch_name: 'sk_rad',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch coincident', 'create_sketch', {
    sketch_name: 'sk_coin',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('create sketch dimension', 'create_sketch', {
    sketch_name: 'sk_dim',
    plane: 'xy',
    cx: '0',
    cy: '0',
    cz: '0',
  });
  await step('draw extrude rectangle', 'draw_rectangle_in_sketch', {
    sketch_name: 'sk_ext',
    x1: '-5',
    y1: '-5',
    x2: '5',
    y2: '5',
  });
  await step('draw revolve rectangle', 'draw_rectangle_in_sketch', {
    sketch_name: 'sk_rev',
    x1: '5',
    y1: '0',
    x2: '8',
    y2: '6',
  });
  await step('draw path line', 'draw_line_in_sketch', {
    sketch_name: 'path1',
    x1: '0',
    y1: '0',
    x2: '0',
    y2: '20',
  });
  await step('draw profile circle', 'draw_circle_in_sketch', {
    sketch_name: 'prof1',
    cx: '0',
    cy: '0',
    radius: '2',
  });
  await step('draw loft circle A', 'draw_circle_in_sketch', {
    sketch_name: 'loftA',
    cx: '0',
    cy: '0',
    radius: '5',
  });
  await step('draw loft circle B', 'draw_circle_in_sketch', {
    sketch_name: 'loftB',
    cx: '0',
    cy: '0',
    radius: '2',
  });

  await step('draw horizontal line', 'draw_line_in_sketch', {
    sketch_name: 'sk_hv',
    x1: '0',
    y1: '0',
    x2: '10',
    y2: '3',
  });
  await step('draw vertical line', 'draw_line_in_sketch', {
    sketch_name: 'sk_v',
    x1: '2',
    y1: '0',
    x2: '8',
    y2: '9',
  });
  await step('draw parallel line 1', 'draw_line_in_sketch', {
    sketch_name: 'sk_par',
    x1: '0',
    y1: '0',
    x2: '10',
    y2: '0',
  });
  await step('draw parallel line 2', 'draw_line_in_sketch', {
    sketch_name: 'sk_par',
    x1: '0',
    y1: '2',
    x2: '10',
    y2: '5',
  });
  await step('draw perpendicular line 1', 'draw_line_in_sketch', {
    sketch_name: 'sk_perp',
    x1: '0',
    y1: '0',
    x2: '10',
    y2: '3',
  });
  await step('draw perpendicular line 2', 'draw_line_in_sketch', {
    sketch_name: 'sk_perp',
    x1: '0',
    y1: '0',
    x2: '3',
    y2: '10',
  });
  await step('draw tangent line', 'draw_line_in_sketch', {
    sketch_name: 'sk_tan',
    x1: '-10',
    y1: '5',
    x2: '10',
    y2: '5',
  });
  await step('draw tangent circle', 'draw_circle_in_sketch', {
    sketch_name: 'sk_tan',
    cx: '0',
    cy: '0',
    radius: '5',
  });
  await step('draw radius circle', 'draw_circle_in_sketch', {
    sketch_name: 'sk_rad',
    cx: '0',
    cy: '0',
    radius: '4',
  });
  await step('draw coincident line 1', 'draw_line_in_sketch', {
    sketch_name: 'sk_coin',
    x1: '0',
    y1: '0',
    x2: '10',
    y2: '0',
  });
  await step('draw coincident line 2', 'draw_line_in_sketch', {
    sketch_name: 'sk_coin',
    x1: '10',
    y1: '0',
    x2: '10',
    y2: '10',
  });
  await step('draw dimension line', 'draw_line_in_sketch', {
    sketch_name: 'sk_dim',
    x1: '0',
    y1: '0',
    x2: '12',
    y2: '5',
  });
  await step('horizontal constraint', 'add_horizontal_constraint', {
    sketch_name: 'sk_hv',
    edge_index: '0',
  });
  await step('vertical constraint', 'add_vertical_constraint', {
    sketch_name: 'sk_v',
    edge_index: '0',
  });
  await step('parallel constraint', 'add_parallel_constraint', {
    sketch_name: 'sk_par',
    edge1: '0',
    edge2: '1',
  });
  await step('perpendicular constraint', 'add_perpendicular_constraint', {
    sketch_name: 'sk_perp',
    edge1: '0',
    edge2: '1',
  });
  await step('tangent constraint', 'add_tangent_constraint', {
    sketch_name: 'sk_tan',
    edge1: '0',
    edge2: '1',
  });
  await step('coincident constraint', 'add_coincident_constraint', {
    sketch_name: 'sk_coin',
    edge1: '0',
    point1: '2',
    edge2: '1',
    point2: '1',
  });
  await step('linear dimension', 'add_linear_dimension', {
    sketch_name: 'sk_dim',
    edge_index: '0',
    distance: '13',
  });
  await step('radius dimension', 'add_radius_dimension', {
    sketch_name: 'sk_rad',
    edge_index: '0',
    radius: '4',
  });

  await step('extrude closed sketch', 'extrude_sketch', {
    sketch_name: 'sk_ext',
    body_name: 'ext1',
    length: '10',
    symmetric: false,
  });

  await step('revolve sketch', 'revolve_sketch', {
    sketch_name: 'sk_rev',
    body_name: 'rev1',
    axis: 'z',
    angle: '300',
  });

  await step('sweep sketch', 'sweep_sketch', {
    profile_sketch: 'prof1',
    path_sketch: 'path1',
    body_name: 'sweep1',
  });

  await step('loft sketches', 'loft_sketches', {
    sketch_names: '["loftA","loftB"]',
    body_name: 'loft1',
    ruled: false,
  });

  await step('section view', 'create_section_view', {
    body_name: 'comboAll',
    plane: 'xy',
    offset: '5',
    new_body_name: 'comboAll_sec',
  });

  await step('execute macro', 'execute_macro', {
    commands: JSON.stringify([
      { tool_name: 'get_all_bodies' },
      { tool_name: 'get_body_dimensions', arguments: { body_name: 'comboAll' } },
    ]),
  }, (r) => ensure(r.executed === 2, 'execute_macro should execute two commands'));

  await step('undo', 'undo', {});
  await step('redo', 'redo', {});

  await step('save document', 'save_document', {
    filename: fcstdPath,
  }, (r) => ensure(fs.existsSync(r.saved), `Saved document not found: ${r.saved}`));

  await step('export STL', 'export_file', {
    body_name: 'comboAll',
    format: 'stl',
    filename: stlPath,
  }, (r) => ensure(fs.existsSync(r.exported_to), `Exported file not found: ${r.exported_to}`));

  const missingTools = toolNames.filter((name) => !usedTools.has(name));
  ensure(
    missingTools.length === 0,
    `Missing regression coverage for tools: ${missingTools.join(', ')}`
  );

  const successful = results.length;
  process.stdout.write(`\nCompleted ${successful} checks.\n`);
  process.stdout.write(`Covered ${usedTools.size}/${toolNames.length} tools.\n`);
  process.stdout.write(`FCStd: ${fcstdPath}\n`);
  process.stdout.write(`STL: ${stlPath}\n`);
}

main().catch((error) => {
  process.stderr.write(`\nFAIL: ${error.message}\n`);
  if (error.payload) {
    process.stderr.write(`${JSON.stringify(error.payload, null, 2)}\n`);
  }
  process.exitCode = 1;
});



