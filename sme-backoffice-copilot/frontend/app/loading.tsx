import { LoadingState } from "./_components/status-states";

export default function Loading() {
  return (
    <LoadingState
      message="Loading the SME operations workspace..."
      title="Opening workspace"
    />
  );
}
