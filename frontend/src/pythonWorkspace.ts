import { stripLatexComments } from "./latexCitations";

export const MAX_INPUT_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_INPUT_TOTAL_BYTES = 20 * 1024 * 1024;
export const MAX_INPUT_FILE_COUNT = 10;
export const MAX_OUTPUT_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_OUTPUT_TOTAL_BYTES = 20 * 1024 * 1024;
export const MAX_OUTPUT_FILE_COUNT = 20;
export const MAX_PYTHON_SOURCE_FILE_COUNT = 20;
export const MAX_PYTHON_SOURCE_FILE_BYTES = 100_000;
export const MAX_PYTHON_SOURCE_TOTAL_BYTES = 500_000;

export type PythonOutput = {
  name: string;
  content: ArrayBuffer;
};

export type PythonSourceFile = {
  filename: string;
  code: string;
};

export function validatePythonSourceFiles(files: ReadonlyArray<PythonSourceFile>): string | null {
  if (!files.length) return "A Python workspace must contain at least one source file.";
  if (files.length > MAX_PYTHON_SOURCE_FILE_COUNT) {
    return `A Python workspace can contain at most ${MAX_PYTHON_SOURCE_FILE_COUNT} source files.`;
  }
  const names = new Set<string>();
  let totalBytes = 0;
  for (const file of files) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,124}\.py$/i.test(file.filename)) {
      return `${file.filename} must be a simple .py filename without path separators.`;
    }
    if (names.has(file.filename.toLowerCase())) {
      return "Python source filenames must be unique regardless of letter case.";
    }
    names.add(file.filename.toLowerCase());
    const bytes = new TextEncoder().encode(file.code).byteLength;
    if (bytes > MAX_PYTHON_SOURCE_FILE_BYTES) {
      return `${file.filename} exceeds the 100 KB source-file limit.`;
    }
    totalBytes += bytes;
    if (totalBytes > MAX_PYTHON_SOURCE_TOTAL_BYTES) {
      return "Python source files exceed the 500 KB workspace limit.";
    }
  }
  if (!files.some((file) => file.filename === "main.py")) {
    return "A source file named exactly main.py is required.";
  }
  return null;
}
export function validatePythonInputs(
  files: ReadonlyArray<Pick<File, "name" | "size">>,
): string | null {
  if (files.length > MAX_INPUT_FILE_COUNT) {
    return `Choose no more than ${MAX_INPUT_FILE_COUNT} CSV or TSV files.`;
  }
  let totalBytes = 0;
  const names = new Set<string>();
  for (const file of files) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(file.name)) {
      return `${file.name} must be a simple filename without path separators.`;
    }
    if (!/\.(csv|tsv)$/i.test(file.name)) {
      return `${file.name} is not a CSV or TSV file.`;
    }
    if (names.has(file.name.toLowerCase())) {
      return "Selected input filenames must be unique.";
    }
    names.add(file.name.toLowerCase());
    if (file.size === 0 || file.size > MAX_INPUT_FILE_BYTES) {
      return `${file.name} must be non-empty and no larger than 5 MB.`;
    }
    totalBytes += file.size;
    if (totalBytes > MAX_INPUT_TOTAL_BYTES) {
      return "Selected input files exceed the 20 MB total limit.";
    }
  }
  return null;
}

export function pythonOutputInsertion(filename: string): string | null {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(filename)) return null;
  if (/\.png$/i.test(filename)) {
    const label = filename.replace(/[^A-Za-z0-9:.-]/g, "-").toLowerCase();
    return [
      "\\begin{figure}[htbp]",
      "\\centering",
      `\\includegraphics[width=0.9\\linewidth]{python-output/${filename}}`,
      `\\caption{${filename.replace(/\.png$/i, "").replace(/[-_]/g, " ")}}`,
      `\\label{fig:${label}}`,
      "\\end{figure}",
    ].join("\n");
  }
  if (/\.tex$/i.test(filename)) return `\\input{python-output/${filename}}`;
  return null;
}

export function pythonOutputPackage(filename: string): string | null {
  if (/\.png$/i.test(filename)) return "graphicx";
  if (/\.tex$/i.test(filename)) return "booktabs";
  return null;
}

export function ensureLatexPackage(source: string, packageName: string): string {
  const uncommented = stripLatexComments(source);
  const packagePattern = new RegExp(
    `\\\\usepackage(?:\\[[^\\]]*\\])?\\s*\\{[^}]*\\b${packageName}\\b[^}]*\\}`,
  );
  if (packagePattern.test(uncommented)) return source;
  const documentClass = uncommented.match(/\\documentclass(?:\[[^\]]*\])?\s*\{[^}]*\}/);
  if (!documentClass || documentClass.index === undefined) {
    return `\\usepackage{${packageName}}\n${source}`;
  }
  const insertionAt = documentClass.index + documentClass[0].length;
  return `${source.slice(0, insertionAt)}\n\\usepackage{${packageName}}${source.slice(insertionAt)}`;
}
