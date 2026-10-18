import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCan } from "./can";
import { keys, useSource } from "./hooks";
import type { AccountLink, AccountProposal } from "./accounts";

export function useAccount(id: string, enabled: boolean) {
  const src = useSource();
  return useQuery({ queryKey: ["account", id], queryFn: () => src.getAccount(id), enabled });
}
export function useLinkAccount(id: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (value: AccountLink) => src.linkAccount(id, value),
    onSuccess: (value) => {
      qc.setQueryData(["account", id], value);
      void qc.invalidateQueries({ queryKey: ["customer"] });
    },
  });
}
export function useProposeAccount(id: string) {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (value: AccountProposal) => src.proposeAccount(id, value),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.approvals });
    },
  });
}
export function useSupportIssues() {
  const src = useSource();
  const enabled = useCan("settings.manage");
  return useQuery({
    queryKey: ["support-issues"],
    queryFn: () => src.listSupportIssues(),
    enabled,
    refetchInterval: 30_000,
  });
}
export function useResolveIssue() {
  const src = useSource();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => src.resolveSupportIssue(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["support-issues"] });
    },
  });
}
