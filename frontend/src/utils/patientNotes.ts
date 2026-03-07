export function getGenderFromNotes(notes: string | null | undefined): string {
  if (!notes) {
    return "";
  }

  const genderLine = notes
    .split("\n")
    .map((line) => line.trim())
    .find((line) => /^gender\s*:/i.test(line));

  if (!genderLine) {
    return "";
  }

  return genderLine.split(":").slice(1).join(":").trim();
}

export function getAgeFromNotes(notes: string | null | undefined): string {
  if (!notes) {
    return "";
  }

  const ageLine = notes
    .split("\n")
    .map((line) => line.trim())
    .find((line) => /^age\s*:/i.test(line));

  if (!ageLine) {
    return "";
  }

  return ageLine.split(":").slice(1).join(":").trim();
}

export function setGenderInNotes(notes: string | null | undefined, gender: string): string | null {
  const trimmedGender = gender.trim();
  const lines = (notes ?? "").split("\n");
  const nextLines: string[] = [];
  let replaced = false;

  for (const line of lines) {
    if (/^gender\s*:/i.test(line.trim())) {
      if (!replaced && trimmedGender) {
        nextLines.push(`Gender: ${trimmedGender}`);
        replaced = true;
      }
      continue;
    }
    nextLines.push(line);
  }

  if (!replaced && trimmedGender) {
    nextLines.unshift(`Gender: ${trimmedGender}`);
  }

  const normalized = nextLines.join("\n").trim();
  return normalized || null;
}

export function removeAgeFromNotes(notes: string | null | undefined): string | null {
  const nextLines = (notes ?? "").split("\n").filter((line) => !/^age\s*:/i.test(line.trim()));
  const normalized = nextLines.join("\n").trim();
  return normalized || null;
}
