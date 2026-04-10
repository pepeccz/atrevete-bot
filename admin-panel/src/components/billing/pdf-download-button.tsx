"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Download, Loader2 } from "lucide-react";
import { billingApi } from "@/lib/billing-api";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface Props {
  invoiceId: string;
  invoiceNumber: string;
  hasPdf: boolean;
  pdfUrl?: string | null;
}

export function PdfDownloadButton({ invoiceId, invoiceNumber, hasPdf, pdfUrl }: Props) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    try {
      setDownloading(true);
      await billingApi.downloadPdf(invoiceId, invoiceNumber, pdfUrl);
    } catch {
      console.error("Error downloading PDF");
    } finally {
      setDownloading(false);
    }
  };

  if (!hasPdf) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="sm" disabled>
              <Download className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>PDF no disponible</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={handleDownload}
      disabled={downloading}
    >
      {downloading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        <Download className="h-4 w-4" />
      )}
    </Button>
  );
}
