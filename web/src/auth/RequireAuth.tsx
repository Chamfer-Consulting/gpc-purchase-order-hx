import { type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Center, Loader, Stack } from "@mantine/core";
import { BrandMark } from "@/components/Brand";
import { useAuth } from "./AuthProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const loc = useLocation();

  if (loading) {
    return (
      <Center h="100vh" bg="var(--gp-page)">
        <Stack align="center" gap="sm">
          <BrandMark size={40} />
          <Loader size="sm" />
        </Stack>
      </Center>
    );
  }
  if (!session) {
    return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  }
  return <>{children}</>;
}
