"use client";

import { useState } from "react";
import { Search, X, Star, Calendar } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Calendar as CalendarComponent } from "@/components/ui/calendar";
import { format } from "date-fns";
import { es } from "date-fns/locale";
import type { NotificationCategory, NotificationQueryParams } from "@/lib/types";
import { NOTIFICATION_CATEGORY_LABELS } from "@/lib/types";

interface NotificationsFiltersProps {
  filters: NotificationQueryParams;
  onFiltersChange: (filters: NotificationQueryParams) => void;
}

export function NotificationsFilters({ filters, onFiltersChange }: NotificationsFiltersProps) {
  const [searchValue, setSearchValue] = useState(filters.search || "");
  const [dateFrom, setDateFrom] = useState<Date | undefined>(
    filters.date_from ? new Date(filters.date_from) : undefined
  );
  const [dateTo, setDateTo] = useState<Date | undefined>(
    filters.date_to ? new Date(filters.date_to) : undefined
  );

  const handleSearchSubmit = () => {
    onFiltersChange({ ...filters, search: searchValue || undefined, page: 1 });
  };

  const handleCategoryChange = (value: string) => {
    onFiltersChange({
      ...filters,
      category: value === "all" ? undefined : (value as NotificationCategory),
      page: 1,
    });
  };

  const handleStatusChange = (value: string) => {
    let isRead: boolean | undefined;
    if (value === "read") isRead = true;
    else if (value === "unread") isRead = false;
    else isRead = undefined;
    onFiltersChange({ ...filters, is_read: isRead, page: 1 });
  };

  const handleStarredChange = (value: string) => {
    let isStarred: boolean | undefined;
    if (value === "starred") isStarred = true;
    else if (value === "not_starred") isStarred = false;
    else isStarred = undefined;
    onFiltersChange({ ...filters, is_starred: isStarred, page: 1 });
  };

  const handleDateFromChange = (date: Date | undefined) => {
    setDateFrom(date);
    onFiltersChange({
      ...filters,
      date_from: date ? format(date, "yyyy-MM-dd") : undefined,
      page: 1,
    });
  };

  const handleDateToChange = (date: Date | undefined) => {
    setDateTo(date);
    onFiltersChange({
      ...filters,
      date_to: date ? format(date, "yyyy-MM-dd") : undefined,
      page: 1,
    });
  };

  const clearFilters = () => {
    setSearchValue("");
    setDateFrom(undefined);
    setDateTo(undefined);
    onFiltersChange({ page: 1, page_size: filters.page_size });
  };

  const hasActiveFilters =
    filters.category ||
    filters.is_read !== undefined ||
    filters.is_starred !== undefined ||
    filters.date_from ||
    filters.date_to ||
    filters.search;

  const activeFilterCount = [
    filters.category,
    filters.is_read !== undefined,
    filters.is_starred !== undefined,
    filters.date_from || filters.date_to,
    filters.search,
  ].filter(Boolean).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Buscar en titulo o mensaje..."
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearchSubmit()}
            className="pl-10"
          />
        </div>

        {/* Category */}
        <Select
          value={filters.category || "all"}
          onValueChange={handleCategoryChange}
        >
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Categoria" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas</SelectItem>
            {Object.entries(NOTIFICATION_CATEGORY_LABELS).map(([key, label]) => (
              <SelectItem key={key} value={key}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Status */}
        <Select
          value={
            filters.is_read === true
              ? "read"
              : filters.is_read === false
              ? "unread"
              : "all"
          }
          onValueChange={handleStatusChange}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Estado" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas</SelectItem>
            <SelectItem value="unread">No leidas</SelectItem>
            <SelectItem value="read">Leidas</SelectItem>
          </SelectContent>
        </Select>

        {/* Starred */}
        <Select
          value={
            filters.is_starred === true
              ? "starred"
              : filters.is_starred === false
              ? "not_starred"
              : "all"
          }
          onValueChange={handleStarredChange}
        >
          <SelectTrigger className="w-[140px]">
            <Star className="h-4 w-4 mr-2" />
            <SelectValue placeholder="Favoritas" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todas</SelectItem>
            <SelectItem value="starred">Favoritas</SelectItem>
            <SelectItem value="not_starred">No favoritas</SelectItem>
          </SelectContent>
        </Select>

        {/* Date From */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className="w-[140px] justify-start text-left font-normal">
              <Calendar className="mr-2 h-4 w-4" />
              {dateFrom ? format(dateFrom, "dd/MM/yy") : "Desde"}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <CalendarComponent
              mode="single"
              selected={dateFrom}
              onSelect={handleDateFromChange}
              locale={es}
              initialFocus
            />
          </PopoverContent>
        </Popover>

        {/* Date To */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className="w-[140px] justify-start text-left font-normal">
              <Calendar className="mr-2 h-4 w-4" />
              {dateTo ? format(dateTo, "dd/MM/yy") : "Hasta"}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <CalendarComponent
              mode="single"
              selected={dateTo}
              onSelect={handleDateToChange}
              locale={es}
              initialFocus
            />
          </PopoverContent>
        </Popover>

        {/* Search button */}
        <Button onClick={handleSearchSubmit}>Buscar</Button>

        {/* Clear filters */}
        {hasActiveFilters && (
          <Button variant="ghost" onClick={clearFilters}>
            <X className="h-4 w-4 mr-2" />
            Limpiar
            {activeFilterCount > 0 && (
              <Badge variant="secondary" className="ml-2">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
        )}
      </div>
    </div>
  );
}
