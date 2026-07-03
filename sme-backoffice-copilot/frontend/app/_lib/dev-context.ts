export const DEFAULT_DEV_TENANT_ID =
  process.env.NEXT_PUBLIC_DEV_TENANT_ID ??
  "00000000-0000-4000-8000-000000000001";

export const DEFAULT_DEV_USER_ID =
  process.env.NEXT_PUBLIC_DEV_USER_ID ?? "00000000-0000-4000-8000-000000000101";

export const DEFAULT_DEV_USER_ROLE =
  process.env.NEXT_PUBLIC_DEV_USER_ROLE ?? "member";

export const DEV_TENANT_STORAGE_KEY = "sme-backoffice.devTenantId";

export type DevOrganization = {
  id: string;
  name: string;
  shortCode: string;
};

export const DEV_ORGANIZATIONS: DevOrganization[] = [
  {
    id: DEFAULT_DEV_TENANT_ID,
    name: "Demo Coffee Co.",
    shortCode: "demo-coffee",
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    name: "Demo Retail Ltd.",
    shortCode: "demo-retail",
  },
];

export function getSelectedTenantId() {
  if (typeof window === "undefined") {
    return DEFAULT_DEV_TENANT_ID;
  }

  return (
    window.localStorage.getItem(DEV_TENANT_STORAGE_KEY) ?? DEFAULT_DEV_TENANT_ID
  );
}
