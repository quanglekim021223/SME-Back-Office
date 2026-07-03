import { ReviewTaskDetailClient } from "./review-task-detail-client";

type ReviewTaskDetailPageProps = {
  params: Promise<{
    taskId: string;
  }>;
};

export default async function ReviewTaskDetailPage({
  params,
}: ReviewTaskDetailPageProps) {
  const { taskId } = await params;

  return <ReviewTaskDetailClient taskId={taskId} />;
}
