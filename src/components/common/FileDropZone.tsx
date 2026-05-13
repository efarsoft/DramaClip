/**
 * 文件拖拽上传区域
 */

import React from 'react';
import { Upload, message } from 'antd';
import { UploadOutlined, VideoCameraOutlined } from '@ant-design/icons';

interface FileDropZoneProps {
  onFilesSelected: (files: string[]) => void;
  accept?: string;
  multiple?: boolean;
  maxSize?: number; // MB
}

export const FileDropZone: React.FC<FileDropZoneProps> = ({
  onFilesSelected,
  accept = 'video/*',
  multiple = true,
  maxSize = 5000,
}) => {
  const validExtensions = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'];

  return (
    <Upload.Dragger
      name="file"
      multiple={multiple}
      accept={accept}
      showUploadList={false}
      beforeUpload={(file: File) => {
        const ext = '.' + file.name.split('.').pop()?.toLowerCase();
        if (!validExtensions.includes(ext)) {
          message.error(`不支持的文件格式：${file.name}`);
          return Upload.LIST_IGNORE;
        }
        const sizeMB = file.size / (1024 * 1024);
        if (sizeMB > maxSize) {
          message.error(`文件过大：${file.name} (${Math.round(sizeMB)}MB > ${maxSize}MB)`);
          return Upload.LIST_IGNORE;
        }
        const filePath = (file as File & { path?: string }).path || file.name;
        onFilesSelected([filePath]);
        return Upload.LIST_IGNORE;
      }}
    >
      <p className="ant-upload-drag-icon">
        <VideoCameraOutlined />
      </p>
      <p className="ant-upload-text">拖拽视频文件到这里，或点击选择</p>
      <p className="ant-upload-hint">
        支持格式：MP4, MKV, AVI, MOV, WMV, FLV, WebM （单文件最大 {maxSize}MB）
      </p>
    </Upload.Dragger>
  );
};

export default FileDropZone;
