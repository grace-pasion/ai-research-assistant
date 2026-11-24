import { describe, expect, it } from "vitest";
import {
  ensureLatexPackage,
  pythonOutputInsertion,
  pythonOutputPackage,
  validatePythonSourceFiles,
  validatePythonInputs,
} from "./pythonWorkspace";

describe("Python source files", () => {
  it("accepts a main script and importable helper files", () => {
    expect(validatePythonSourceFiles([
      { filename: "main.py", code: "from helpers import total\nprint(total())" },
      { filename: "helpers.py", code: "def total(): return 42" },
    ])).toBeNull();
  });

  it("requires safe, unique filenames and a main.py entry point", () => {
    expect(validatePythonSourceFiles([
      { filename: "main.py", code: "" },
      { filename: "MAIN.PY", code: "" },
    ])).toContain("unique");
    expect(validatePythonSourceFiles([
      { filename: "../main.py", code: "" },
    ])).toContain("simple .py filename");
    expect(validatePythonSourceFiles([
      { filename: "MAIN.PY", code: "" },
    ])).toContain("main.py");
    expect(validatePythonSourceFiles([
      { filename: "helpers.py", code: "" },
    ])).toContain("main.py");
  });

  it("enforces source workspace size limits", () => {
    const files = Array.from({ length: 20 }, (_, index) => ({
      filename: index === 0 ? "main.py" : `module${index}.py`,
      code: "",
    }));
    expect(validatePythonSourceFiles(files)).toBeNull();
    expect(validatePythonSourceFiles([
      ...files,
      { filename: "extra.py", code: "" },
    ])).toContain("at most 20");
  });
});

describe("Python workspace inputs", () => {
  it("accepts selected CSV and TSV files within the limits", () => {
    expect(validatePythonInputs([
      { name: "study.csv", size: 12 },
      { name: "codes.tsv", size: 24 },
    ])).toBeNull();
  });

  it("rejects unsafe, unsupported, duplicated, and oversized inputs", () => {
    expect(validatePythonInputs([{ name: "../study.csv", size: 10 }])).toContain("simple filename");
    expect(validatePythonInputs([{ name: "study.xlsx", size: 10 }])).toContain("CSV or TSV");
    expect(validatePythonInputs([
      { name: "study.csv", size: 10 },
      { name: "STUDY.CSV", size: 10 },
    ])).toContain("unique");
    expect(validatePythonInputs([{ name: "study.csv", size: 5 * 1024 * 1024 + 1 }])).toContain("5 MB");
  });
});

describe("Python output insertion", () => {
  it("inserts safe figure and TeX table references", () => {
    expect(pythonOutputInsertion("effect_plot.png")).toContain(
      "\\includegraphics[width=0.9\\linewidth]{python-output/effect_plot.png}",
    );
    expect(pythonOutputInsertion("summary_table.tex")).toBe(
      "\\input{python-output/summary_table.tex}",
    );
    expect(pythonOutputInsertion("data.csv")).toBeNull();
    expect(pythonOutputInsertion("../figure.png")).toBeNull();
  });

  it("adds the LaTeX package needed by each inserted output type", () => {
    expect(pythonOutputPackage("effect_plot.png")).toBe("graphicx");
    expect(pythonOutputPackage("summary_table.tex")).toBe("booktabs");
    expect(pythonOutputPackage("data.csv")).toBeNull();
  });

  it("adds graphicx only when it is not already loaded", () => {
    const source = "\\documentclass{article}\n\\begin{document}\nText";
    expect(ensureLatexPackage(source, "graphicx")).toBe(
      "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\nText",
    );
    expect(ensureLatexPackage(`${source}\n\\usepackage{graphicx}`, "graphicx")).toBe(
      `${source}\n\\usepackage{graphicx}`,
    );
    expect(ensureLatexPackage(
      `\\documentclass{article}\n% \\usepackage{graphicx}\n\\begin{document}`,
      "graphicx",
    )).toContain("\\usepackage{graphicx}\n\\begin{document}");
  });
});
