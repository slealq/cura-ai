'use client';

import LibraryImage from '@/components/LibraryImage';

import { Suspense, useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { editApi, settingsApi, billingApi } from '@/lib/api';
import { Loader2, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import PaintCanvas, { maskFile, type PaintMask } from '@/components/tools/PaintCanvas';
import BoxCanvas, { type Box, type ObjectBox } from '@/components/tools/BoxCanvas';
import Stage from '@/components/tools/Stage';
import SheetButton from '@/components/tools/SheetButton';
import SubjectSlots from '@/components/tools/SubjectSlots';
import JobTabs, { jobs, type EditJob } from '@/components/tools/JobTabs';
import Notice from '@/components/tools/Notice';
import ModelPanel from '@/components/tools/ModelPanel';
import Composer from '@/components/tools/Composer';
import SourceTray from '@/components/tools/SourceTray';
import SubjectPanel from '@/components/tools/SubjectPanel';
import { useSearchParams } from 'next/navigation';
import { imagesApi } from '@/lib/api';
import ImagePickerModal from '@/components/ImagePickerModal';

import { useModelCatalog } from '@/hooks/useModelCatalog';
import { cn } from '@/lib/utils';

const SIZE_PRESETS = [
  { label: 'Square HD', value: 'square_hd' },
  { label: 'Square', value: 'square' },
  { label: 'Portrait 4:3', value: 'portrait_4_3' },
  { label: 'Portrait 16:9', value: 'portrait_16_9' },
  { label: 'Landscape 4:3', value: 'landscape_4_3' },
  { label: 'Landscape 16:9', value: 'landscape_16_9' },
];

interface SourceImage {
  type: 'gallery' | 'generated' | 'upload';
  id?: number;
  key?: string;
  previewUrl?: string;
  name?: string;
  role?: 'reference' | 'element_main' | 'element_angle';
  element?: number;
}

function formatDuration(createdAt: string, completedAt: string | null): string | null {
  if (!completedAt) return null;
  const ms = new Date(completedAt).getTime() - new Date(createdAt).getTime();
  if (ms < 0) return null;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

export default function EditPage() {
  return (
    <Suspense fallback={<div className="grid h-32 place-items-center"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>}>
      <EditPageInner />
    </Suspense>
  );
}

function EditPageInner() {
  const queryClient = useQueryClient();
  const params = useSearchParams();
  const [job, setJob] = useState<EditJob>(() => {
    const requested = params.get('job');
    return requested && requested in jobs ? requested as EditJob : 'describe';
  });
  const [notice, setNotice] = useState('');
  const hasInitEditModel = useRef(false);
  const appliedJob = useRef<string | null>(null);
  const changedSettings = useRef(new Set<string>());

  // Form state
  const [prompt, setPrompt] = useState('');
  const [negativePrompt, setNegativePrompt] = useState('');
  const [editModel, setEditModel] = useState('');
  const [quality, setQuality] = useState('');
  const { data: catalog } = useModelCatalog();
  const EDIT_MODELS = useMemo(() => (catalog?.edit ?? []).map(m => ({ value: m.key, label: m.label })), [catalog]);
  const model = catalog?.edit.find(m => m.key === editModel);
  const spec = model?.params ?? {};
  const KLING_RESOLUTIONS = (spec.resolution?.options ?? []).map(value => ({ value, label: value }));
  const KLING_ASPECT_RATIOS = (spec.aspect_ratio?.options ?? []).map(value => ({ value, label: value }));
  const SAFETY_LEVELS = (spec.safety_tolerance?.options ?? []).map(value => ({ value, label: value }));
  const [imageSize, setImageSize] = useState<string>('square_hd');
  const [customWidth, setCustomWidth] = useState(1024);
  const [customHeight, setCustomHeight] = useState(1024);
  const [useCustomSize, setUseCustomSize] = useState(false);
  const [numImages, setNumImages] = useState(1);
  const [resultType, setResultType] = useState<'single' | 'series'>('single');
  const [seriesAmount, setSeriesAmount] = useState(2);
  const [elementCount, setElementCount] = useState(1);
  const outputCount = job === 'subject' && resultType === 'series' ? seriesAmount : numImages;
  const [seed, setSeed] = useState<string>('');
  const [enablePromptExpansion, setEnablePromptExpansion] = useState(true);
  const [enableSafetyChecker, setEnableSafetyChecker] = useState(true);
  // Kling-specific state
  const [resolution, setResolution] = useState('1K');
  const [aspectRatio, setAspectRatio] = useState('auto');
  // Nano Banana Pro state
  const [safetyTolerance, setSafetyTolerance] = useState('4');
  const [enableWebSearch, setEnableWebSearch] = useState(false);
  // Fetch default edit model from settings
  const { data: editModelData } = useQuery({
    queryKey: ['edit-model'],
    queryFn: settingsApi.getEditModel,
  });

  const estimateParams = {
    base_model: editModel, operation: 'edit' as const,
    ...(job === 'subject' && resultType === 'series' ? { result_type: resultType, series_amount: seriesAmount } : {}),
    ...(spec.resolution && resolution ? { resolution } : {}),
    ...(spec.quality && quality ? { quality } : {}),
    ...(spec.image_size && imageSize ? { image_size: imageSize } : {}),
    ...(spec.enable_web_search ? { enable_web_search: enableWebSearch } : {}),
    ...(useCustomSize ? { width: customWidth, height: customHeight } : {}),
  };
  const { data: estimate } = useQuery({
    queryKey: ['edit-estimate', estimateParams],
    queryFn: () => billingApi.estimateGenerationCost(estimateParams),
    enabled: !!model,
  });

  // Initialize edit model from settings
  useEffect(() => {
    if (catalog && editModelData && !hasInitEditModel.current) {
      hasInitEditModel.current = true;
      if (EDIT_MODELS.some((m) => m.value === editModelData.edit_model)) {
        setEditModel(editModelData.edit_model);
      } else { setEditModel(catalog.defaults.edit_model); }
    }
  }, [editModelData, catalog, EDIT_MODELS]);

  useEffect(() => {
    const requested = params.get('job');
    if (!requested || !(requested in jobs) || !catalog || !editModel || appliedJob.current === requested) return;
    appliedJob.current = requested;
    setJob(requested as EditJob);
    if (!catalog.edit.find(item => item.key === editModel)?.jobs.includes(requested as EditJob)) {
      const supported = catalog.edit.find(item => item.jobs.includes(requested as EditJob));
      if (supported) setEditModel(supported.key);
    }
  }, [params, catalog, editModel]);

  const caps = {
    maxSources: job === 'subject' ? 10 + elementCount * 4 : job === 'paint' && editModel === 'ideogram-v4.5-edit' ? 4 : model?.max_source_images ?? 1, maxImages: model?.max_num_images || 1,
    hasNegativePrompt: !!spec.negative_prompt, hasPromptExpansion: false, hasSafetyChecker: false,
    usesResolution: !!(spec.resolution || spec.aspect_ratio), hasImageSize: !!spec.image_size,
    hasSeed: !!spec.seed, maxPromptLen: 8000, hasSafetyTolerance: !!spec.safety_tolerance, hasWebSearch: !!spec.enable_web_search
  };
  useEffect(() => {
    if (!model) return;
    setResolution(spec.resolution?.default ?? '');
    setAspectRatio(spec.aspect_ratio?.default ?? '');
    setImageSize(spec.image_size?.default ?? '');
    setSafetyTolerance(spec.safety_tolerance?.default ?? '');
    setQuality(spec.quality?.default ?? '');
    setUseCustomSize(false);
  }, [model, spec.resolution?.default, spec.aspect_ratio?.default, spec.image_size?.default, spec.safety_tolerance?.default, spec.quality?.default]);

  // Source images state
  const [sources, setSources] = useState<SourceImage[]>([]);
  const [masks, setMasks] = useState<Record<string, PaintMask>>({});
  const baseKey = sources[0] ? `${sources[0].type}-${sources[0].id ?? sources[0].previewUrl}` : '';
  const mask = masks[baseKey];
  const [layouts, setLayouts] = useState<Record<string, ObjectBox[]>>({});
  const [regions, setRegions] = useState<Record<string, { area: 'none' | 'auto' | 'box'; box?: Box }>>({});
  const [selectedBox, setSelectedBox] = useState(0);
  const [drawPrecision, setDrawPrecision] = useState(false);
  const [boxPart, setBoxPart] = useState<'source_box' | 'target_box'>('target_box');
  const objects = layouts[baseKey] ?? [];
  const region = regions[baseKey] ?? { area: 'none' as const };
  function setObjects(next: ObjectBox[]) {
    setLayouts(current => ({ ...current, [baseKey]: next }));
  }
  function updateObject(index: number, patch: Partial<ObjectBox>) {
    setLayouts(current => ({ ...current, [baseKey]: (current[baseKey] ?? []).map((object, i) => i === index ? { ...object, ...patch } : object) }));
  }
  const objectsInvalid = !objects.length || objects.some(object => !/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(object.label) || !object.description.trim() || (object.action !== 'Place' && !object.source_box) || (object.action !== 'Remove' && !object.target_box)) || new Set(objects.map(object => object.label)).size !== objects.length;

  const [baseUrl, setBaseUrl] = useState<string>();
  useEffect(() => {
    let active = true;
    const base = sources[0];
    setBaseUrl(undefined);
    if (base?.type === 'gallery' && base.id) {
      imagesApi.get(base.id).then(image => {
        if (active) setBaseUrl(imagesApi.getImageUrl(image.object_key.split('/').pop()!));
      }).catch(() => toast.error('Could not load full size base'));
    } else if (base?.type === 'generated' && base.id) {
      setBaseUrl(editApi.getImageUrl(base.id));
    } else setBaseUrl(base?.previewUrl);
    return () => { active = false; };
  }, [sources]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    const ids = (params.get('sources') || '').split(',').map(Number).filter(id => Number.isInteger(id) && id > 0);
    setSources(ids.map(id => ({ type: 'gallery', id, previewUrl: undefined })));
    let active = true;
    ids.forEach(async (id) => {
      try {
        const image = await imagesApi.get(id);
        const thumbnail = image.thumbnail_uri_medium || image.thumbnail_uri_small;
        const previewUrl = thumbnail
          ? imagesApi.getThumbnailUrl(thumbnail.split('/').pop()!)
          : imagesApi.getImageUrl(image.object_key.split('/').pop()!);
        if (active) {
          setSources(current => current.map(source => (
            source.type === 'gallery' && source.id === id ? { ...source, previewUrl } : source
          )));
        }
      } catch {
        if (active) toast.error(`Could not load source ${id}`);
      }
    });
    return () => { active = false; };
  }, [params]);

  // Full-size modal
  const [selectedImageId, setSelectedImageId] = useState<number | null>(null);
  // Fetch edited images with polling
  const { data: editedImages } = useQuery({
    queryKey: ['edited-images'],
    queryFn: () => editApi.listImages({ limit: 100 }),
    // Poll only while a result is on its way; starting an edit invalidates this query.
    refetchInterval: query => query.state.data?.items.some(image => image.status === 'pending' || image.status === 'generating') ? 3000 : false,
  });

  // Edit mutation
  const editMutation = useMutation({
    mutationFn: editApi.edit,
    onSuccess: (data) => {
      toast.success(`Edit started (${data.generated_image_ids.length} images)`, { action: { label: 'View Jobs', onClick: () => { window.location.href = '/jobs'; } } });
      queryClient.invalidateQueries({ queryKey: ['edited-images'] });
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (err: Error) => {
      toast.error(`Edit failed: ${err.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: editApi.deleteImage,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['edited-images'] });
    },
    onError: (err: Error) => {
      toast.error(`Delete failed: ${err.message}`);
    },
  });

  const handleEdit = async () => {
    if (!prompt.trim()) {
      toast.error('Please enter a prompt');
      return;
    }
    if (sources.length === 0) {
      toast.error('Please add at least one source image');
      return;
    }
    if (sources.length > caps.maxSources) {
      toast.error(`Maximum ${caps.maxSources} source images for this model`);
      return;
    }

    const params: Parameters<typeof editApi.edit>[0] = {
      edit_model: editModel,
      num_images: job === 'subject' && resultType === 'series' ? 1 : numImages,
      prompt: prompt.trim(),
    };

    if (caps.usesResolution) {
      if (spec.resolution && resolution) params.resolution = resolution;
      if (spec.aspect_ratio && aspectRatio) params.aspect_ratio = aspectRatio;
    }
    if (caps.hasImageSize) {
      if (useCustomSize) {
        params.image_size = { width: customWidth, height: customHeight };
      } else if (imageSize) {
        params.image_size = imageSize;
      }
    }
    if (caps.hasNegativePrompt && negativePrompt.trim()) {
      params.negative_prompt = negativePrompt.trim();
    }
    if (caps.hasPromptExpansion) {
      params.enable_prompt_expansion = enablePromptExpansion;
    }
    if (caps.hasSafetyChecker) {
      params.enable_safety_checker = enableSafetyChecker;
    }
    if (caps.hasSafetyTolerance) {
      params.safety_tolerance = safetyTolerance;
    }
    if (caps.hasWebSearch) {
      params.enable_web_search = enableWebSearch;
    }
    if (caps.hasSeed && seed) params.seed = parseInt(seed);
    if (spec.quality && quality) params.quality = quality;

    params.ordered_sources = sources.map(({ type, id, key, name, role, element }) => ({ type, id, key, name, ...(job === 'subject' ? { role: role ?? 'reference', element } : {}) }));
    if (job === 'subject') {
      if (subjectInvalid) return toast.error('Assign a main photo to each subject and keep up to 10 composition references');
      params.result_type = resultType;
      if (resultType === 'series') params.series_amount = seriesAmount;
    }

    if (job === 'objects') {
      if (objectsInvalid) return toast.error('Give each box a unique valid name, description and required areas');
      params.object_boxes = objects;
    }
    if (job === 'paint') {
      if (editModel === 'ideogram-v4.5-edit') {
        if (region.area === 'box' && !region.box) return toast.error('Draw the precision area first');
        params.precision_area = region.area;
        if (region.area === 'box') params.precision_box = region.box;
      }
      if (!mask?.percent) return toast.error('Paint an area before applying');
      if (editModel === 'ideogram-v4.5-edit' && mask.percent === 100) return toast.error('Leave part of the base unpainted for Ideogram');
      setUploading(true);
      try {
        const uploaded = await editApi.uploadSource(await maskFile(mask));
        params.mask_key = uploaded.object_key;
        if (editModel === 'ideogram-v4.5-edit') params.image_size = 'auto';
        editMutation.mutate(params);
      } catch (error) {
        toast.error(`Mask upload failed: ${(error as Error).message}`);
      } finally {
        setUploading(false);
      }
    } else editMutation.mutate(params);
  };



  const maxSources = caps.maxSources;

  const handleFileUpload = useCallback(async (files: FileList | File[]) => {
    const remaining = maxSources - sources.length;
    if (remaining <= 0) {
      toast.error(`Maximum ${maxSources} source images`);
      return;
    }

    const filesToProcess = Array.from(files).slice(0, remaining).filter(file => {
      if (file.size <= 30 * 1024 * 1024) return true;
      toast.error(`${file.name} is too large (max 30MB)`);
      return false;
    });
    if (files.length > remaining) toast.info(`Only ${remaining} sources can be added for this model`);
    const pending = filesToProcess.map(file => ({ file, previewUrl: URL.createObjectURL(file) }));
    setSources(current => [...current, ...pending.map(({ file, previewUrl }) => ({ type: 'upload' as const, name: file.name, previewUrl }))]);
    setUploading(true);
    try {
      for (const { file, previewUrl } of pending) {
        try {
          const result = await editApi.uploadSource(file);
          setSources(current => current.map(source => source.previewUrl === previewUrl ? { ...source, key: result.object_key } : source));
        } catch (err) {
          setSources(current => current.filter(source => source.previewUrl !== previewUrl));
          URL.revokeObjectURL(previewUrl);
          toast.error(`Upload failed for ${file.name}: ${(err as Error).message}`);
        }
      }
    } finally {
      setUploading(false);
    }
  }, [sources.length, maxSources]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.files.length > 0) {
        handleFileUpload(e.dataTransfer.files);
      }
    },
    [handleFileUpload]
  );

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData.items;
      const imageFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const file = items[i].getAsFile();
          if (file) imageFiles.push(file);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        handleFileUpload(imageFiles);
      }
    },
    [handleFileUpload]
  );

  const handlePickerDone = (items: import('@/components/ImagePickerModal').PickedImage[]) => {
    const newSources: SourceImage[] = items.map((item) => ({
      type: item.type,
      id: item.id,
      previewUrl: item.previewUrl,
    }));
    setSources((prev) => [...prev, ...newSources]);
  };

  const images = editedImages?.items || [];
  const selectedImage = selectedImageId != null
    ? images.find((img) => img.id === selectedImageId) ?? null
    : null;

  const alreadySelectedIds = sources.filter((s) => s.type === 'gallery' || s.type === 'generated').map((s) => s.id!);

  function changeModel(key: string, reason = '') {
    if (key === editModel) return;
    const target = catalog?.edit.find(m => m.key === key);
    if (!target) return;
    const notes = [reason];
    const count = Math.min(numImages, target.max_num_images || 1);
    if (count !== numImages) notes.push(`Results changed to ${count}.`);
    const settings = [
      ['Resolution', resolution, target.params.resolution?.default ?? ''],
      ['Aspect ratio', aspectRatio, target.params.aspect_ratio?.default ?? ''],
      ['Image size', imageSize, target.params.image_size?.default ?? ''],
      ['Safety tolerance', safetyTolerance, target.params.safety_tolerance?.default ?? ''],
      ['Quality', quality, target.params.quality?.default ?? ''],
    ];
    settings.forEach(([label, previous, next]) => {
      if (changedSettings.current.has(label) && previous !== next) notes.push(next ? `${label} changed to ${next}.` : `${label} removed.`);
    });
    if (useCustomSize) notes.push('Custom size cleared.');
    if (negativePrompt) notes.push('Negative prompt cleared.');
    if (seed) notes.push('Seed cleared.');
    if (enableWebSearch) notes.push('Web search turned off.');
    setNegativePrompt('');
    setSeed('');
    setEnableWebSearch(false);
    changedSettings.current.clear();
    setNotice(notes.filter(Boolean).join(' '));
    setNumImages(count);
    setEditModel(key);
  }

  const subjectInvalid = job === 'subject' && (
    prompt.length > 2500 || sources.filter(source => !source.role || source.role === 'reference').length > 10 ||
    Array.from({ length: elementCount }, (_, i) => i + 1).some(element => !sources.some(source => source.element === element && source.role === 'element_main'))
  );
  let referenceIndex = 0;
  const subjectLabels = sources.map(source => source.element ? `@Element${source.element} · ${source.role === 'element_main' ? 'main' : 'angle'}` : `@Image${++referenceIndex}`);

  const sourceTray = (
    <SourceTray
      sources={sources}
      model={editModel}
      labels={job === 'subject' ? subjectLabels : undefined}
      overLimit={job === 'subject' ? subjectLabels.map(label => label.startsWith('@Image') && Number(label.slice(6)) > 10) : undefined}
      limit={maxSources}
      onChange={setSources}
      onAdd={() => setPickerOpen(true)}
      onUpload={handleFileUpload}
      onUse={(label) => setPrompt(current => `${current} ${label.split(' · ')[0]}`.trim())}
    />
  );

  const results = images.length > 0 ? (
    <div aria-label="Results" className="flex shrink-0 items-center gap-1 overflow-x-auto">
      <span className="mr-1 text-xs text-muted-foreground">Results</span>
      {images.filter(image => image.status !== 'failed').sort((a, b) => b.id - a.id).map((image) => (
        <button
          key={image.id}
          onClick={() => setSelectedImageId(image.id)}
          aria-label={`Open edited image ${image.id}${image.status === 'completed' ? '' : `, ${image.status}`}`}
          className={`relative h-[52px] w-[52px] shrink-0 overflow-hidden rounded-[5px] bg-muted ${image.status === 'pending' || image.status === 'processing' ? 'animate-[shimmer_1.3s_linear_infinite] bg-gradient-to-r from-muted via-accent to-muted bg-[length:220%_100%]' : ''}`}
        >
          {image.status === 'completed' && image.object_key ? (
            <LibraryImage src={editApi.getImageUrl(image.id)} alt={image.prompt} className="h-full w-full object-cover" />
          ) : image.status === 'failed' ? (
            <span className="text-xs text-destructive">Failed</span>
          ) : <span className="sr-only">Generating</span>}
        </button>
      ))}
    </div>
  ) : null;

  const objectControls = (
              <div className="space-y-3">
                <p className="text-xs text-muted-foreground">Move and Remove use the first source image. Names start with a letter and contain letters, numbers or underscores.</p>
                {objects.map((object, index) => (
                  <div key={index} className="space-y-2 border-b border-border pb-3">
                    <button className="text-xs text-primary" aria-pressed={selectedBox === index} onClick={() => setSelectedBox(index)}>Draw object {index + 1}</button>
                    <label className="block text-xs">Name, used as &lt;{object.label}&gt;
                      <input className="mt-1 w-full rounded border border-input bg-background p-2" maxLength={64} pattern="[A-Za-z][A-Za-z0-9_]*" value={object.label} onChange={event => updateObject(index, { label: event.target.value })} />
                    </label>
                    <label className="block text-xs">What’s in this box
                      <input className="mt-1 w-full rounded border border-input bg-background p-2" maxLength={500} value={object.description} onChange={event => updateObject(index, { description: event.target.value })} />
                    </label>
                    <label className="block text-xs">Action
                      <select className="mt-1 w-full rounded border border-input bg-background p-2" value={object.action} onChange={event => updateObject(index, { action: event.target.value as ObjectBox['action'], ...(window.matchMedia('(max-width: 767px)').matches ? { source_box: object.source_box ?? object.target_box ?? { x_min: 0.3, y_min: 0.3, x_max: 0.7, y_max: 0.7 }, target_box: object.target_box ?? object.source_box ?? { x_min: 0.3, y_min: 0.3, x_max: 0.7, y_max: 0.7 } } : {}) })}>
                        {(['Place', 'Move', 'Remove'] as const).map(action => <option key={action}>{action}</option>)}
                      </select>
                    </label>
                    <p className="text-xs text-muted-foreground">Source: {object.source_box ? 'drawn' : 'not drawn'} · Target: {object.target_box ? 'drawn' : 'not drawn'}</p>
                    {object.action === 'Move' && selectedBox === index && (
                      <select aria-label="Area to draw" className="w-full rounded border border-input bg-background p-2 text-xs" value={boxPart} onChange={event => setBoxPart(event.target.value as typeof boxPart)}>
                        <option value="source_box">Draw source area</option>
                        <option value="target_box">Draw target area</option>
                      </select>
                    )}
                    <button className="text-xs text-muted-foreground" onClick={() => { setObjects(objects.filter((_, i) => i !== index)); setSelectedBox(0); }}>Delete box</button>
                  </div>
                ))}
                <button className="rounded border border-border px-2 py-1 text-xs" disabled={objects.length >= 32} onClick={() => {
                  let number = objects.length + 1;
                  while (objects.some(object => object.label === `object_${number}`)) number++;
                  setObjects([...objects, { label: `object_${number}`, description: '', action: 'Place', ...(window.matchMedia('(max-width: 767px)').matches ? { target_box: { x_min: 0.3, y_min: 0.3, x_max: 0.7, y_max: 0.7 } } : {}) }]);
                  setSelectedBox(objects.length);
                }}>+ Add box ({objects.length}/32)</button>
              </div>
  );

  return (
    <div className="-mx-5 -my-5 h-[calc(100%+40px)] min-h-0">
      <style jsx global>{`
        @keyframes shimmer {
          to { background-position: -220% 0; }
        }
      `}</style>
      <Stage
        mobileSheets={{
          Model: <ModelPanel models={catalog?.edit ?? []} job={job} value={editModel} onChange={changeModel} />,
          'Object details': objectControls,
        }}
        tabs={
          <JobTabs
            value={job}
            onChange={(next) => {
              setNotice(job === 'subject' && next !== 'subject' && (resultType === 'series' || sources.some(source => source.element)) ? 'Subject assignments and series settings are kept for Keep a subject. This job uses ordinary sources and its Results count.' : '');
              setJob(next);
              if (next === 'paint' && editModel === 'ideogram-v4.5-edit' && (imageSize !== 'auto' || useCustomSize)) {
                setImageSize('auto');
                setUseCustomSize(false);
                setNotice('Image size changed to auto for Ideogram paint.');
              }
              if (!model?.jobs.includes(next)) {
                const target = catalog?.edit.find(m => m.jobs.includes(next));
                if (target) changeModel(target.key, `Switched to ${target.label} for this job. Your images are kept.`);
              }
            }}
          />
        }
        canvas={
          <div
            onPaste={handlePaste}
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDrop}
            className="flex min-h-0 flex-1 flex-col gap-2.5"
          >
            
            {job === 'paint' && editModel === 'ideogram-v4.5-edit' && region.area === 'box' && (
              <button className="self-start rounded border border-border px-2 py-1 text-xs" onClick={() => setDrawPrecision(!drawPrecision)}>{drawPrecision ? 'Paint inside area' : 'Draw precision area'}</button>
            )}
            <div hidden={job !== 'paint' || (editModel === 'ideogram-v4.5-edit' && region.area === 'box' && drawPrecision)}>
              <PaintCanvas region={editModel === 'ideogram-v4.5-edit' && region.area === 'box' ? region.box : undefined} source={baseUrl} value={mask} onChange={value => setMasks(current => ({ ...current, [baseKey]: value }))} />
            </div>
            {job === 'objects' && (
              <BoxCanvas key={baseKey} source={baseUrl} selected={selectedBox} onSelect={setSelectedBox} staticBoxes={objects.flatMap(object => object.action === 'Move' && object.source_box && boxPart === 'target_box' ? [{ label: `${object.label} · source`, box: object.source_box }] : [])} boxes={objects.map(object => ({ label: `${object.label} · ${object.action === 'Place' ? 'target' : object.action === 'Remove' ? 'source' : boxPart === 'source_box' ? 'source' : 'target'}`, box: object[object.action === 'Place' ? 'target_box' : object.action === 'Remove' ? 'source_box' : boxPart] }))} onChange={box => {
                const object = objects[selectedBox];
                if (object) updateObject(selectedBox, { [object.action === 'Place' ? 'target_box' : object.action === 'Remove' ? 'source_box' : boxPart]: box });
              }} />
            )}
            {job === 'objects' && (
              <div className="flex justify-between gap-2 md:hidden">
                <SheetButton title="Object details" label={`Edit ${objects[selectedBox]?.label || 'box'}`} />
                <button className="min-h-10 rounded border px-3" disabled={objects.length >= 32} onClick={() => {
                  let number = objects.length + 1;
                  while (objects.some(object => object.label === `object_${number}`)) number++;
                  setObjects([...objects, { label: `object_${number}`, description: '', action: 'Place', target_box: { x_min: 0.3, y_min: 0.3, x_max: 0.7, y_max: 0.7 } }]);
                  setSelectedBox(objects.length);
                }}>+ Box</button>
              </div>
            )}
            {job === 'subject' && <>
              <SubjectSlots sources={sources} count={elementCount} onCount={setElementCount} onChange={setSources} onAdd={() => setPickerOpen(true)} />
              <SheetButton title="Subject photos and references">{sourceTray}</SheetButton>
            </>}
            {job === 'paint' && editModel === 'ideogram-v4.5-edit' && region.area === 'box' && drawPrecision && (
              <BoxCanvas key={`region-${baseKey}`} source={baseUrl} selected={0} boxes={[{ label: 'Precision area', box: region.box }]} onChange={box => setRegions(current => ({ ...current, [baseKey]: { area: 'box', box } }))} />
            )}
            {job === 'paint' || job === 'objects' ? (
              <>
              <div className="md:hidden"><SheetButton title="References" label={`Sources and references (${sources.length})`}>{sourceTray}</SheetButton></div>
              <details className="hidden shrink-0 md:block">
                <summary className="cursor-pointer text-xs text-muted-foreground">
                  Sources and references ({sources.length}) · first image is the base
                </summary>
                {sourceTray}
              </details>
              </>
            ) : job === 'subject' ? <div className="hidden md:contents">{sourceTray}</div> : sourceTray}
            {results}
          </div>
        }
        composer={
          <Composer
            value={prompt}
            onChange={setPrompt}
            onApply={handleEdit}
            disabled={subjectInvalid || (job === 'objects' && objectsInvalid) || (job === 'paint' && editModel === 'ideogram-v4.5-edit' && region.area === 'box' && !region.box) || (job === 'paint' && (!mask?.percent || (editModel === 'ideogram-v4.5-edit' && mask.percent === 100))) || !model || editMutation.isPending || uploading || !prompt.trim() || !sources.length || sources.length > maxSources}
            model={model?.label}
            count={outputCount}
            warning={subjectInvalid ? 'Assign each subject a main photo; up to 3 angles, 10 references and 2500 prompt characters' : job === 'objects' && objectsInvalid ? 'Name and describe each object, then draw its areas' : job === 'paint' && !mask?.percent ? 'Paint the area first' : job === 'paint' && editModel === 'ideogram-v4.5-edit' && mask?.percent === 100 ? 'Leave part of the image unpainted' : sources.length > maxSources ? `This model takes up to ${maxSources} sources. Remove ${sources.length - maxSources}.` : !sources.length ? 'Add a source image' : uploading ? 'Uploading sources…' : undefined}
            cost={estimate?.estimated_sparks != null ? estimate.estimated_sparks * (job === 'subject' && resultType === 'series' ? 1 : numImages) : undefined}
          />
        }
        settings={
          <>
            <h2 className="text-sm font-semibold">{jobs[job]}</h2>
            <Notice>{notice}</Notice>
            <ModelPanel
              models={catalog?.edit ?? []}
              job={job}
              value={editModel}
              onChange={changeModel}
            />
            <label className="block text-xs text-muted-foreground">
              {job === 'subject' && resultType === 'series' ? 'Series images' : 'Results'}
              <select
                className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-[13px] text-foreground"
                value={outputCount}
                onChange={(event) => job === 'subject' && resultType === 'series' ? setSeriesAmount(Number(event.target.value)) : setNumImages(Number(event.target.value))}
              >
                {Array.from({ length: job === 'subject' && resultType === 'series' ? 8 : caps.maxImages }, (_, i) => (
                  <option key={i + 1}>{i + (job === 'subject' && resultType === 'series' ? 2 : 1)}</option>
                ))}
              </select>
            </label>
            <div><span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">Sources: {maxSources}</span></div>
            <div className="space-y-3 border-t border-border pt-2.5">
              <h3 className="text-[12.5px] font-medium">Advanced for this model</h3>
            {job === 'subject' && (
              <SubjectPanel sources={sources} count={elementCount} onCount={setElementCount} onChange={setSources} onUse={label => setPrompt(current => `${current} ${label}`.trim())} />
            )}
            {job === 'paint' && editModel === 'ideogram-v4.5-edit' && (
              <>
              <label className="block text-xs text-muted-foreground">Precision area
                <select className="mt-1 w-full rounded-md border border-input bg-background p-2" value={region.area} onChange={event => { setDrawPrecision(event.target.value === 'box'); setRegions(current => ({ ...current, [baseKey]: { ...region, area: event.target.value as 'none' | 'auto' | 'box' } })); }}>
                  <option value="none">None</option>
                  <option value="auto">Auto</option>
                  <option value="box">Drawn box</option>
                </select>
              </label>
              <p className="text-xs text-muted-foreground">Ideogram can change more than the area you paint. Only a drawn box keeps everything outside it untouched.</p>
              </>
            )}
            {job === 'objects' && objectControls}
              {/* Negative prompt */}
              {caps.hasNegativePrompt && (
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Negative Prompt</label>
                  <input
                    type="text"
                    value={negativePrompt}
                    onChange={(e) => setNegativePrompt(e.target.value.slice(0, 500))}
                    placeholder="Things to avoid..."
                    className="w-full px-3 py-2 border border-border rounded-lg text-sm"
                  />
                </div>
              )}

              {/* Resolution + Aspect Ratio (Kling) */}
              {caps.usesResolution && (
                <div className="flex flex-col gap-3">
                  {spec.resolution && (
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">Resolution</label>
                      <div className="flex flex-wrap gap-2">
                        {KLING_RESOLUTIONS.map((r) => (
                          <button
                            key={r.value}
                            onClick={() => {
                              changedSettings.current.add('Resolution');
                              setResolution(r.value);
                            }}
                            className={cn(
                              'px-4 py-1.5 text-xs border rounded-lg transition-colors',
                              resolution === r.value
                                ? 'border-primary bg-primary/5 text-primary'
                                : 'border-border hover:bg-muted'
                            )}
                          >
                            {r.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {spec.aspect_ratio && (
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">Aspect Ratio</label>
                      <select
                        value={aspectRatio}
                        onChange={(event) => {
                          changedSettings.current.add('Aspect ratio');
                          setAspectRatio(event.target.value);
                        }}
                        className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                      >
                        {KLING_ASPECT_RATIOS.map((ar) => (
                          <option key={ar.value} value={ar.value}>{ar.label}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {spec.quality && (
                <label className="block text-xs text-muted-foreground">
                  Quality
                  <select
                    value={quality}
                    onChange={(event) => {
                      changedSettings.current.add('Quality');
                      setQuality(event.target.value);
                    }}
                    className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1.5 text-[13px] text-foreground"
                  >
                    {spec.quality.options?.map(value => (
                      <option key={value} value={value}>{value}</option>
                    ))}
                  </select>
                </label>
              )}
              {/* Size presets (Qwen/FLUX). Seedream requires its own named enum. */}
              {caps.hasImageSize && !(job === 'paint' && editModel === 'ideogram-v4.5-edit') && (
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Image Size</label>
                  <div className="flex flex-wrap gap-2">
                    {(spec.image_size?.options ?? []).map(value => ({ value, label: value.replaceAll("_", " ") })).map((preset) => (
                      <button
                        key={preset.value}
                        onClick={() => {
                          changedSettings.current.add('Image size');
                          setImageSize(preset.value);
                          setUseCustomSize(false);
                        }}
                        className={cn(
                          'px-3 py-1.5 text-xs border rounded-lg transition-colors',
                          !useCustomSize && imageSize === preset.value
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-border hover:bg-muted'
                        )}
                      >
                        {preset.label}
                      </button>
                    ))}
                    {spec.image_size?.custom_size && (
                      <button
                        onClick={() => setUseCustomSize(true)}
                        className={cn(
                          'px-3 py-1.5 text-xs border rounded-lg transition-colors',
                          useCustomSize
                            ? 'border-primary bg-primary/5 text-primary'
                            : 'border-border hover:bg-muted'
                        )}
                      >
                        Custom
                      </button>
                    )}
                  </div>
                  {useCustomSize && (
                    <div className="flex gap-2 mt-2">
                      <div>
                        <label className="text-xs text-muted-foreground">Width</label>
                        <input
                          type="number"
                          value={customWidth}
                          onChange={(e) => setCustomWidth(parseInt(e.target.value) || 1024)}
                          min={256}
                          max={2048}
                          className="w-full min-w-0 px-2 py-1 border border-border rounded-lg text-sm"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground">Height</label>
                        <input
                          type="number"
                          value={customHeight}
                          onChange={(e) => setCustomHeight(parseInt(e.target.value) || 1024)}
                          min={256}
                          max={2048}
                          className="w-full min-w-0 px-2 py-1 border border-border rounded-lg text-sm"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="flex flex-col gap-3">
                {/* Seed */}
                {caps.hasSeed && (
                  <div>
                    <label className="block text-xs text-muted-foreground mb-1">Seed</label>
                    <input
                      type="text"
                      value={seed}
                      onChange={(e) => setSeed(e.target.value.replace(/\D/g, ''))}
                      placeholder="Random"
                      className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                    />
                  </div>
                )}

              </div>

              {/* Toggles */}
              {(caps.hasPromptExpansion || caps.hasSafetyChecker) && (
                <div className="flex flex-wrap gap-6">
                  {caps.hasPromptExpansion && (
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={enablePromptExpansion}
                        onChange={(e) => setEnablePromptExpansion(e.target.checked)}
                        className="rounded"
                      />
                      Prompt expansion
                    </label>
                  )}
                  {caps.hasSafetyChecker && (
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={enableSafetyChecker}
                        onChange={(e) => setEnableSafetyChecker(e.target.checked)}
                        className="rounded"
                      />
                      Safety checker
                    </label>
                  )}
                </div>
              )}

              {/* Safety Tolerance + Web Search */}
              {(caps.hasSafetyTolerance || caps.hasWebSearch) && (
                <div className="flex flex-col gap-3">
                  {caps.hasSafetyTolerance && (
                    <div>
                      <label className="block text-xs text-muted-foreground mb-1">Safety Tolerance</label>
                      <select
                        value={safetyTolerance}
                        onChange={(event) => {
                          changedSettings.current.add('Safety tolerance');
                          setSafetyTolerance(event.target.value);
                        }}
                        className="w-full px-3 py-1.5 border border-border rounded-lg text-sm"
                      >
                        {SAFETY_LEVELS.map((s) => (
                          <option key={s.value} value={s.value}>{s.label}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  {caps.hasWebSearch && (
                    <div className="flex items-end pb-1">
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={enableWebSearch}
                          onChange={(e) => setEnableWebSearch(e.target.checked)}
                          className="rounded"
                        />
                        Enable web search
                      </label>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        }
      />


      {/* Full-size modal */}
      {selectedImage && (
        <>
          <div
            className="fixed inset-0 bg-black/70 z-50"
            onClick={() => setSelectedImageId(null)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div
              className="bg-card rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-4 border-b border-border">
                <h3 className="font-semibold">Edited Image #{selectedImage.id}</h3>
                <button
                  aria-label="Delete edited image"
                  onClick={() => {
                    deleteMutation.mutate(selectedImage.id);
                    setSelectedImageId(null);
                  }}
                  className="ml-auto mr-3 rounded p-1 text-destructive hover:bg-muted"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                <button
                  onClick={() => setSelectedImageId(null)}
                  className="p-1 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
              <div className="p-4 space-y-4">
                {selectedImage.status === 'completed' && selectedImage.object_key ? (
                  <LibraryImage
                    src={editApi.getImageUrl(selectedImage.id)}
                    alt={selectedImage.prompt}
                    className="max-w-full mx-auto rounded-lg"
                  />
                ) : (
                  <div className="flex items-center justify-center h-64 bg-muted/30 rounded-lg">
                    {selectedImage.status === 'failed' ? (
                      <p className="text-red-600 text-sm">{selectedImage.error_message || 'Edit failed'}</p>
                    ) : (
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    )}
                  </div>
                )}
                <div className="space-y-3 text-sm">
                  <div>
                    <span className="font-medium">Prompt:</span>
                    <p className="text-muted-foreground mt-0.5">{selectedImage.prompt}</p>
                  </div>
                  {selectedImage.negative_prompt && (
                    <div>
                      <span className="font-medium">Negative Prompt:</span>
                      <p className="text-muted-foreground mt-0.5">{selectedImage.negative_prompt}</p>
                    </div>
                  )}
                  {(() => {
                    const gp = (selectedImage.generation_params || {}) as Record<string, unknown>;
                    const duration = formatDuration(selectedImage.created_at, selectedImage.completed_at);
                    const modelLabel = EDIT_MODELS.find((m) => m.value === selectedImage.base_model)?.label || selectedImage.base_model;
                    return (
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 bg-muted/30 rounded-lg p-3">
                        <div>
                          <span className="text-xs text-muted-foreground">Model</span>
                          <p className="font-medium">{modelLabel}</p>
                        </div>
                        {selectedImage.width != null && selectedImage.height != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Output Size</span>
                            <p className="font-medium">{selectedImage.width} x {selectedImage.height}</p>
                          </div>
                        )}
                        {duration && (
                          <div>
                            <span className="text-xs text-muted-foreground">Duration</span>
                            <p className="font-medium">{duration}</p>
                          </div>
                        )}
                        {gp.actual_seed != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Seed</span>
                            <p className="font-medium">{String(gp.actual_seed)}</p>
                          </div>
                        )}
                        {typeof gp.image_size === 'string' && (
                          <div>
                            <span className="text-xs text-muted-foreground">Size Preset</span>
                            <p className="font-medium">{SIZE_PRESETS.find((p) => p.value === gp.image_size)?.label || String(gp.image_size)}</p>
                          </div>
                        )}
                        {typeof gp.image_size === 'object' && gp.image_size !== null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Requested Size</span>
                            <p className="font-medium">{(gp.image_size as { width: number; height: number }).width} x {(gp.image_size as { width: number; height: number }).height}</p>
                          </div>
                        )}
                        {'resolution' in gp && gp.resolution != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Resolution</span>
                            <p className="font-medium">{String(gp.resolution)}</p>
                          </div>
                        )}
                        {'aspect_ratio' in gp && gp.aspect_ratio != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Aspect Ratio</span>
                            <p className="font-medium">{String(gp.aspect_ratio)}</p>
                          </div>
                        )}
                        {'output_format' in gp && gp.output_format != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Format</span>
                            <p className="font-medium uppercase">{String(gp.output_format)}</p>
                          </div>
                        )}
                        {'enable_prompt_expansion' in gp && gp.enable_prompt_expansion != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Prompt Expansion</span>
                            <p className="font-medium">{gp.enable_prompt_expansion ? 'On' : 'Off'}</p>
                          </div>
                        )}
                        {'enable_safety_checker' in gp && gp.enable_safety_checker != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Safety Checker</span>
                            <p className="font-medium">{gp.enable_safety_checker ? 'On' : 'Off'}</p>
                          </div>
                        )}
                        {'safety_tolerance' in gp && gp.safety_tolerance != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Safety Tolerance</span>
                            <p className="font-medium">{String(gp.safety_tolerance)}</p>
                          </div>
                        )}
                        {'enable_web_search' in gp && gp.enable_web_search != null && (
                          <div>
                            <span className="text-xs text-muted-foreground">Web Search</span>
                            <p className="font-medium">{gp.enable_web_search ? 'On' : 'Off'}</p>
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Image Picker Modal */}
      <ImagePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onDone={handlePickerDone}
        alreadySelectedIds={alreadySelectedIds}
        maxSelection={Math.max(0, maxSources - sources.filter(source => source.type === 'upload').length)}
      />
    </div>
  );
}
