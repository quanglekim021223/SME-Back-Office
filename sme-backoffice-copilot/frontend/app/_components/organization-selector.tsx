"use client";

import { useEffect, useState } from "react";

import {
  DEV_ORGANIZATIONS,
  DEV_TENANT_STORAGE_KEY,
  DEFAULT_DEV_TENANT_ID,
} from "../_lib/dev-context";

export function OrganizationSelector() {
  const [selectedTenantId, setSelectedTenantId] = useState(
    DEFAULT_DEV_TENANT_ID,
  );

  useEffect(() => {
    const storedTenantId = window.localStorage.getItem(DEV_TENANT_STORAGE_KEY);

    if (
      storedTenantId &&
      DEV_ORGANIZATIONS.some(
        (organization) => organization.id === storedTenantId,
      )
    ) {
      setSelectedTenantId(storedTenantId);
    }
  }, []);

  function handleTenantChange(nextTenantId: string) {
    setSelectedTenantId(nextTenantId);
    window.localStorage.setItem(DEV_TENANT_STORAGE_KEY, nextTenantId);
  }

  const selectedOrganization = DEV_ORGANIZATIONS.find(
    (organization) => organization.id === selectedTenantId,
  );

  return (
    <section className="organization-card" aria-label="Organization selector">
      <label htmlFor="organization-selector">Organization</label>
      <select
        id="organization-selector"
        onChange={(event) => handleTenantChange(event.target.value)}
        value={selectedTenantId}
      >
        {DEV_ORGANIZATIONS.map((organization) => (
          <option key={organization.id} value={organization.id}>
            {organization.name}
          </option>
        ))}
      </select>
      <p>
        Placeholder tenant:{" "}
        <code>{selectedOrganization?.shortCode ?? "unknown"}</code>
      </p>
    </section>
  );
}
