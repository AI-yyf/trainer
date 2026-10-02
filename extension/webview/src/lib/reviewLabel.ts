/** Display legacy review keys without changing the concept used for grading. */
export function reviewConceptLabel(concept: string): string {
  const value = concept.trim();
  if (!/:next-step$/i.test(value)) {
    return value;
  }
  return value
    .replace(/:next-step$/i, "")
    .replace(/^trainer[-:]/i, "")
    .replace(/-/g, " ")
    .replace(/\bpython\b/gi, "Python")
    .trim();
}
