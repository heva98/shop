import {
  AlertCircle, ArrowDown, ArrowLeftRight, ArrowUp, BarChart3, Building2, Calendar, CalendarClock, Check, CheckCircle2,
  ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Clock, Download, ExternalLink, FileText, Filter, Folder, Globe,
  GripVertical, Info, LayoutDashboard, LayoutGrid, Lock, LogOut, Mail, MapPin, Maximize2, Menu as MenuIcon, MessageSquare, MoreHorizontal,
  BadgePercent, BookUser, Package, PackageCheck, PackageX, PanelLeftClose, PanelLeftOpen, Pencil, Plus, Printer, RefreshCw,
  Database, Layers, Pin, PinOff, SlidersHorizontal, Table2, Wand2,
  Save, ScanBarcode, Search, Settings, Share2, ShoppingBag, ShoppingCart, Star, Store, Trash2, TrendingUp, TriangleAlert, Upload, UserRound, Users, Wallet, X,
} from 'lucide-react'
import icons from './icons.generated.js'

// Lucide-style 2px stroke icons (DESIGN.md › Iconography). Names are the
// app's own; the old "-16"/"-24" svg set is only a fallback for unmapped names.
const LUCIDE = {
  dashboard: LayoutDashboard, 'dashboard-window': LayoutDashboard, pos: ShoppingCart, table: ShoppingCart,
  stock: Package, receiving: PackageCheck, transfer: ArrowLeftRight, share: Share2, customers: BookUser,
  analytics: BarChart3, 'visualization-bar': BarChart3, 'visualization-line': TrendingUp, reports: FileText,
  'file-document': FileText, settings: Settings, admin: Building2, folder: Folder, add: Plus, download: Download,
  upload: Upload, location: MapPin, cross: X, 'chevron-down': ChevronDown, 'chevron-up': ChevronUp,
  'chevron-left': ChevronLeft, 'chevron-right': ChevronRight, info: Info, 'info-filled': Info,
  'checkmark-circle': CheckCircle2, checkmark: Check, error: AlertCircle, 'error-filled': AlertCircle,
  warning: TriangleAlert, brand: ShoppingBag, store: Store, search: Search, 'log-out': LogOut, user: UserRound,
  'user-group': Users, 'panel-close': PanelLeftClose, 'panel-open': PanelLeftOpen, more: MoreHorizontal,
  clock: Clock, wallet: Wallet, 'package-x': PackageX, expiry: CalendarClock, calendar: Calendar, edit: Pencil,
  delete: Trash2, print: Printer, 'arrow-up': ArrowUp, 'arrow-down': ArrowDown, mail: Mail, sync: RefreshCw,
  filter: Filter, lock: Lock, star: Star, save: Save, world: Globe, fullscreen: Maximize2, messages: MessageSquare,
  apps: LayoutGrid, 'drag-handle': GripVertical, launch: ExternalLink, menu: MenuIcon, promotion: BadgePercent,
  barcode: ScanBarcode, database: Database, layers: Layers, pin: Pin, 'pin-off': PinOff, sliders: SlidersHorizontal,
  'pivot-table': Table2, wand: Wand2,
}

export default function Icon({ name, size = 18, style, className, strokeWidth = 2 }) {
  if (!name) return null
  const Lucide = LUCIDE[name]
  if (Lucide) {
    return <Lucide size={size} strokeWidth={strokeWidth} className={className} style={{ flex: `0 0 ${size}px`, ...style }} aria-hidden="true" />
  }
  const svg = icons[`${name}-${size}`] || icons[`${name}-24`]
  if (!svg) return null
  return (
    <span
      className={className}
      aria-hidden="true"
      style={{ display: 'inline-flex', width: size, height: size, flex: `0 0 ${size}px`, ...style }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
