type Props = {
  filters: string[];
};

export function ActiveFilterSummary({ filters }: Props) {
  if (!filters.length) return null;

  return (
    <div className="active-filter-summary">
      <span className="active-filter-summary-label">Active filters</span>
      {filters.map((filter) => (
        <span className="active-filter-chip" key={filter}>{filter}</span>
      ))}
    </div>
  );
}
