/// <reference lib="webworker" />

import { loadPyodide } from "pyodide";
import {
  MAX_OUTPUT_FILE_BYTES,
  MAX_OUTPUT_FILE_COUNT,
  MAX_OUTPUT_TOTAL_BYTES,
  type PythonSourceFile,
} from "./pythonWorkspace";

type WorkerInput = {
  requestId: number;
  entrypoint: string;
  files: PythonSourceFile[];
  inputs: Array<{ name: string; content: ArrayBuffer }>;
};

type WorkerOutput = {
  requestId: number;
  stdout: string;
  error: string | null;
  warnings: string[];
  outputs: Array<{ name: string; content: ArrayBuffer }>;
};

type Pyodide = Awaited<ReturnType<typeof loadPyodide>>;

const workerScope = self as DedicatedWorkerGlobalScope;
const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v314.0.8/full/";
const MAX_CAPTURED_OUTPUT_CHARS = 50_000;
let pyodidePromise: Promise<Pyodide> | null = null;

function getPyodide(): Promise<Pyodide> {
  if (!pyodidePromise) {
    pyodidePromise = loadPyodide({
      indexURL: PYODIDE_INDEX_URL,
      jsglobals: {},
    })
      .then(async (pyodide) => {
        await pyodide.loadPackage(["numpy", "pandas", "matplotlib", "jinja2"]);
        pyodide.runPython("import matplotlib\nmatplotlib.use('Agg')");
        return pyodide;
      })
      .catch((cause: unknown) => {
        pyodidePromise = null;
        throw cause;
      });
  }
  return pyodidePromise;
}

function clearDirectory(pyodide: Pyodide, path: string): void {
  pyodide.runPython(`
import os
import shutil
directory = ${JSON.stringify(path)}
os.makedirs(directory, exist_ok=True)
for name in os.listdir(directory):
    child = os.path.join(directory, name)
    if os.path.islink(child) or not os.path.isdir(child):
        os.unlink(child)
    else:
        shutil.rmtree(child)
`);
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

async function runPython(message: WorkerInput): Promise<WorkerOutput> {
  const pyodide = await getPyodide();
  pyodide.runPython("import os\nos.chdir('/home/pyodide')");
  clearDirectory(pyodide, "/inputs");
  clearDirectory(pyodide, "/outputs");
  clearDirectory(pyodide, "/workspace");
  pyodide.runPython("import os\nos.chdir('/workspace')");
  if (!message.files.some((source) => source.filename === message.entrypoint)) {
    throw new Error("The selected Python source file no longer exists.");
  }
  for (const source of message.files) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,124}\.py$/i.test(source.filename)) {
      throw new Error(`Unsupported Python source filename: ${source.filename}`);
    }
    pyodide.FS.writeFile(`/workspace/${source.filename}`, new TextEncoder().encode(source.code));
  }
  for (const input of message.inputs) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(csv|tsv)$/i.test(input.name)) {
      throw new Error(`Unsupported input filename: ${input.name}`);
    }
    pyodide.FS.writeFile(`/inputs/${input.name}`, new Uint8Array(input.content));
  }

  pyodide.globals.set("_entrypoint", message.entrypoint);
  pyodide.globals.set(
    "_source_modules_json",
    JSON.stringify(message.files.map((source) => source.filename.slice(0, -3))),
  );
  let error: string | null = null;
  try {
    pyodide.runPython(`
import contextlib
import importlib
import io
import json
import os
import runpy
import sys
if "/workspace" not in sys.path:
    sys.path.insert(0, "/workspace")
for module_name in json.loads(_source_modules_json):
    sys.modules.pop(module_name, None)
importlib.invalidate_caches()
class _LimitedCapture(io.StringIO):
    def write(self, text):
        remaining = ${MAX_CAPTURED_OUTPUT_CHARS} - self.tell()
        if remaining > 0:
            super().write(text[:remaining])
        return len(text)
_capture = _LimitedCapture()
with contextlib.redirect_stdout(_capture), contextlib.redirect_stderr(_capture):
    runpy.run_path(os.path.join("/workspace", _entrypoint), run_name="__main__")
`);
  } catch (cause) {
    error = errorText(cause);
  }

  const stdout = String(pyodide.runPython("_capture.getvalue()"));
  const truncated = Boolean(pyodide.runPython("_capture.tell() >= 50000"));
  const entries = pyodide.FS.readdir("/outputs").filter((name) => name !== "." && name !== "..");
  if (entries.length > MAX_OUTPUT_FILE_COUNT) {
    throw new Error(`A run can create at most ${MAX_OUTPUT_FILE_COUNT} outputs.`);
  }
  const outputs: WorkerOutput["outputs"] = [];
  const warnings: string[] = [];
  let totalBytes = 0;
  const names = new Set<string>();
  for (const name of entries) {
    const path = `/outputs/${name}`;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(png|csv|tsv|tex)$/i.test(name)
      || !pyodide.FS.isFile(pyodide.FS.stat(path).mode)) {
      warnings.push(`Ignored unsupported output: ${name}`);
      continue;
    }
    if (names.has(name.toLowerCase())) {
      throw new Error("Output filenames must be unique regardless of letter case.");
    }
    names.add(name.toLowerCase());
    const bytes = pyodide.FS.readFile(path);
    if (!bytes.length) throw new Error(`${name} is empty.`);
    if (bytes.length > MAX_OUTPUT_FILE_BYTES) {
      throw new Error(`${name} exceeds the 5 MB per-file limit.`);
    }
    totalBytes += bytes.length;
    if (totalBytes > MAX_OUTPUT_TOTAL_BYTES) {
      throw new Error("Generated outputs exceed the 20 MB total limit.");
    }
    const extension = name.slice(name.lastIndexOf(".")).toLowerCase();
    if (extension === ".png") {
      const signature = [137, 80, 78, 71, 13, 10, 26, 10];
      if (!signature.every((byte, index) => bytes[index] === byte)) {
        throw new Error(`${name} is not a valid PNG file.`);
      }
    } else {
      new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    }
    outputs.push({ name, content: new Uint8Array(bytes).buffer });
  }
  const outputText = truncated ? `${stdout}\n[Python output truncated at 50,000 characters.]` : stdout;
  if (error) return { requestId: message.requestId, stdout: outputText, error, warnings, outputs: [] };
  return { requestId: message.requestId, stdout: outputText, error: null, warnings, outputs };
}

workerScope.onmessage = async (event: MessageEvent<WorkerInput>) => {
  const message = event.data;
  try {
    const result = await runPython(message);
    workerScope.postMessage(result, result.outputs.map((output) => output.content));
  } catch (cause) {
    workerScope.postMessage({
      requestId: message.requestId,
      stdout: "",
      error: errorText(cause),
      warnings: [],
      outputs: [],
    } satisfies WorkerOutput);
  }
};
