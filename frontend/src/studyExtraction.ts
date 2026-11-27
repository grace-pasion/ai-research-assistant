import type { PaperStudyExtraction } from "./types";

export type StudyExtractionValues = Pick<
  PaperStudyExtraction,
  "population" | "methods" | "sample_size" | "outcomes" | "limitations"
>;

export const STUDY_EXTRACTION_FIELDS = [
  { name: "population", label: "Population", maxLength: 10_000 },
  { name: "methods", label: "Methods", maxLength: 10_000 },
  { name: "sample_size", label: "Sample size", maxLength: 2_000 },
  { name: "outcomes", label: "Outcomes", maxLength: 10_000 },
  { name: "limitations", label: "Limitations", maxLength: 10_000 },
] as const satisfies readonly {
  name: keyof StudyExtractionValues;
  label: string;
  maxLength: number;
}[];

export function studyExtractionValues(
  extraction: PaperStudyExtraction | null | undefined,
): StudyExtractionValues {
  return {
    population: extraction?.population ?? "",
    methods: extraction?.methods ?? "",
    sample_size: extraction?.sample_size ?? "",
    outcomes: extraction?.outcomes ?? "",
    limitations: extraction?.limitations ?? "",
  };
}

export function hasStudyExtractionChanges(
  draft: StudyExtractionValues,
  saved: PaperStudyExtraction | null | undefined,
): boolean {
  const current = studyExtractionValues(saved);
  return STUDY_EXTRACTION_FIELDS.some(({ name }) => draft[name] !== current[name]);
}
