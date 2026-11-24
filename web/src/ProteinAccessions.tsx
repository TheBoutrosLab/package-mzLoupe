import { useState } from "react";
import { Button, Popover, Stack, Text, UnstyledButton } from "@mantine/core";
import type { ProteinGroupingAssignment } from "./api";

interface Props {
  accessions: string[];
  grouping?: ProteinGroupingAssignment;
}

/** Keep original identifiers and inference order separate from compact labels. */
export class ProteinLabels {
  /** Abbreviate UniProt labels without stripping decoy or contaminant prefixes. */
  static compact(accession: string): string {
    const uniprot = /^(?:sp|tr)\|([^|]+)\|[^|]+$/.exec(accession);
    return uniprot?.[1] ?? accession;
  }

  /** Summarize one group without mixing its other members with another group. */
  static groupLabel(group: ProteinGroupingAssignment["groups"][number]): string {
    const representative = ProteinLabels.compact(group.members[0]);
    const additional = group.members.length - 1;
    return additional > 0 ? `${representative} (+${additional})` : representative;
  }

  /** Describe one assigned group, ambiguity, or the original mapping fallback. */
  static selection(proteins: string[], grouping?: ProteinGroupingAssignment) {
    if (!grouping) {
      return {
        representative: proteins[0],
        label: ProteinLabels.compact(proteins[0]),
        additional: proteins.length - 1
      };
    }
    if (grouping.status === "assigned" && grouping.groups.length === 1) {
      const members = grouping.groups[0].members;
      return {
        representative: members[0],
        label: ProteinLabels.compact(members[0]),
        additional: members.length - 1
      };
    }
    if (grouping.status === "ambiguous" && grouping.groups.length) {
      return {
        representative: grouping.groups.map((group) => group.members[0]).join("; "),
        label: grouping.groups.map(ProteinLabels.groupLabel).join("; "),
        additional: 0
      };
    }
    return {
      representative: "",
      label: grouping.status === "ambiguous" ? "Unresolved group" : "Not assigned",
      additional: 0
    };
  }
}

/** Inspect shared-peptide mappings without triggering the surrounding PSM row. */
export function ProteinAccessions({ accessions, grouping }: Props) {
  const [copyStatus, setCopyStatus] = useState("");
  // Alphabetical ordering is only a fallback for original search mappings.
  const proteins = [...new Set(accessions)].filter(Boolean).sort();
  if (!proteins.length && !grouping) {
    return <span title="No protein mappings reported">—</span>;
  }
  const selection = ProteinLabels.selection(proteins, grouping);
  const title = grouping
    ? `${grouping.name}: ${selection.label}`
    : selection.representative;
  const accessibleLabel = grouping
    ? `Show protein grouping: ${title}`
    : `Show ${proteins.length} protein${proteins.length === 1 ? "" : "s"}: ${selection.representative}`;

  /** Copy full accessions, including database and decoy/contaminant prefixes. */
  async function copyAccessions(values: string[]) {
    try {
      await navigator.clipboard.writeText(values.join("\n"));
      setCopyStatus("Copied");
    } catch {
      setCopyStatus("Copy unavailable. Select and copy the list below.");
    }
  }

  return (
    // React portal events still bubble to the PSM row, so isolate the dropdown too.
    <div
      className="protein-accessions"
      onClick={(event) => event.stopPropagation()}
    >
      <Popover
        width={360}
        position="bottom-start"
        withinPortal
        withArrow
        trapFocus
        returnFocus
        onChange={() => setCopyStatus("")}
      >
        <Popover.Target>
          <UnstyledButton
            className="protein-accessions-button"
            aria-label={accessibleLabel}
            title={title}
          >
            <span className="protein-representative">{selection.label}</span>
            {selection.additional > 0 && (
              <span className="protein-count">+{selection.additional}</span>
            )}
          </UnstyledButton>
        </Popover.Target>
        <Popover.Dropdown className="protein-popover">
          <Stack gap="xs">
            {grouping && (
              <GroupingDetails
                grouping={grouping}
                onCopy={copyAccessions}
              />
            )}
            <Text fw={600}>
              {grouping ? "Original peptide mappings" : "Mapped proteins"} (
              {proteins.length})
            </Text>
            {!grouping && (
              <Text size="xs">
                First accession shown alphabetically; no leading protein inferred.
              </Text>
            )}
            <Button
              size="xs"
              variant="light"
              onClick={() => copyAccessions(proteins)}
            >
              {grouping ? "Copy original mappings" : "Copy all"}
            </Button>
            {copyStatus && (
              <Text
                size="xs"
                role="status"
              >
                {copyStatus}
              </Text>
            )}
            <AccessionList accessions={proteins} />
          </Stack>
        </Popover.Dropdown>
      </Popover>
    </div>
  );
}

interface DetailsProps {
  grouping: ProteinGroupingAssignment;
  onCopy: (accessions: string[]) => Promise<void>;
}

/** Keep inferred peptide links, group members, and original evidence distinct. */
function GroupingDetails({ grouping, onCopy }: DetailsProps) {
  const collection =
    grouping.collection === "protein_groups"
      ? "Protein groups"
      : "Indistinguishable proteins";
  const basis =
    grouping.basis === "accession_overlap"
      ? "Accession overlap"
      : "Inference peptide evidence";

  return (
    <>
      <Text fw={600}>{grouping.name}</Text>
      <Text size="xs">
        {collection} · {basis}
      </Text>
      {grouping.status === "ambiguous" && (
        <Text size="sm">No unique group assignment.</Text>
      )}
      {grouping.status === "unassigned" && (
        <Text size="sm">No matching group for this peptide.</Text>
      )}
      {!!grouping.inferred_accessions?.length && (
        <>
          <Text size="sm">Inference peptide mappings</Text>
          <AccessionList accessions={grouping.inferred_accessions} />
        </>
      )}
      <div className="protein-group-details">
        {grouping.groups.map((group) => (
          <div key={group.id}>
            <Text size="sm">Representative: {group.members[0]}</Text>
            <Text size="xs">
              Probability:{" "}
              {group.probability == null ? "Not supplied" : group.probability}
            </Text>
            <Button
              size="xs"
              variant="light"
              onClick={() => onCopy(group.members)}
            >
              Copy group members
            </Button>
            <AccessionList accessions={group.members} />
          </div>
        ))}
      </div>
    </>
  );
}

/** Show selectable, original accession text with bounded scrolling. */
function AccessionList({ accessions }: { accessions: string[] }) {
  return (
    <ul className="protein-accession-list">
      {accessions.map((accession) => (
        <li key={accession}>{accession}</li>
      ))}
    </ul>
  );
}
